"""Time photo denoise and sharpen on a seeded synthetic print at three scan sizes.

Run: ``uv run python tools/diagnostics/bench_photo_detail.py [--runs 3] [--sizes 300 600 8x10]``.

Sizes: 4x6 in at 300 dpi (1200x1800), 4x6 in at 600 dpi (2400x3600) and 8x10 in at 600 dpi
(4800x6000). Stages, each at strength 50: luma, chroma, both, sharpen, all. Each row is the median
of ``--runs`` timed runs at one OpenCV thread and at the default thread count, in seconds and in
seconds per megapixel. Also printed: the OpenCV version, the CPU model, peak RSS of the process, and
two sanity numbers (flat-patch luma noise before and after, 10-90% edge width before and after).
The print is synthetic, so none of this says anything about real scans or picture quality. No
paths, user names or hostnames are printed. Not used by the app or CI.
"""

import argparse
import resource
import statistics
import time
from collections.abc import Callable
from threading import Event

import cv2
import numpy as np

from fastfoto_linux.photo_edits import PhotoDetail
from fastfoto_linux.photo_edits.detail import apply_denoise, apply_sharpen

INCH_SIZES = {"300": (4, 6, 300), "600": (4, 6, 600), "8x10": (8, 10, 600)}
STAGES = {
    "luma": PhotoDetail(50, 0, 0),
    "chroma": PhotoDetail(0, 50, 0),
    "both": PhotoDetail(50, 50, 0),
    "sharpen": PhotoDetail(0, 0, 50),
    "all": PhotoDetail(50, 50, 50),
}
LUMA_NOISE_SIGMA = 6.0
CHROMA_NOISE_SIGMA = 4.0
SEED = 20261029
CHUNK_ROWS = 512
FLAT_RGB = (150, 130, 110)
EDGE_HIGH = 200.0
EDGE_REACH = 16
EDGE_TAIL = 4
RISE_LOW, RISE_HIGH = 0.1, 0.9
MEGAPIXEL = 1e6
KIB = 1024
DEFAULT_RUNS = 3


def make_print(width: int, height: int, *, noisy: bool = True) -> np.ndarray:
    """Gradients, a bright block with sharp edges, a flat patch, then luma and chroma noise."""
    rng = np.random.default_rng(SEED)
    image = np.empty((height, width, 3), dtype=np.uint8)
    columns = np.linspace(0.0, 1.0, width, dtype=np.float32)
    regions = ((_block(width, height), (EDGE_HIGH,) * 3), (_flat_patch(width, height), FLAT_RGB))
    for top in range(0, height, CHUNK_ROWS):
        rows = min(CHUNK_ROWS, height - top)
        ramp = np.linspace(top / height, (top + rows) / height, rows, dtype=np.float32)
        base = np.empty((rows, width, 3), dtype=np.float32)
        base[..., 0] = 90 + 80 * ramp[:, None]
        base[..., 1] = 100 + 50 * columns[None, :]
        base[..., 2] = 140 - 40 * columns[None, :]
        for (y, x), color in regions:
            lo, hi = max(y.start, top) - top, min(y.stop, top + rows) - top
            if lo < hi:
                base[lo:hi, x] = color
        if noisy:
            base += rng.standard_normal((rows, width, 1), dtype=np.float32) * LUMA_NOISE_SIGMA
            chroma = rng.standard_normal((rows, width, 3), dtype=np.float32) * CHROMA_NOISE_SIGMA
            base += chroma - chroma.mean(axis=2, keepdims=True)
        image[top : top + rows] = np.clip(base + 0.5, 0, 255).astype(np.uint8)
    return image


def _flat_patch(width: int, height: int) -> tuple[slice, slice]:
    return slice(height // 20, height // 5), slice(width // 20, width // 5)


def _block(width: int, height: int) -> tuple[slice, slice]:
    return slice(height // 3, 2 * height // 3), slice(width // 3, 2 * width // 3)


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _crossing(profile: np.ndarray, level: float) -> float:
    """The first fractional index where a rising profile reaches `level`."""
    index = int(np.argmax(profile >= level))
    if index == 0:
        return 0.0
    step = profile[index] - profile[index - 1]
    return index - 1 + (level - profile[index - 1]) / step


def edge_width(rgb: np.ndarray, width: int, height: int) -> float:
    """10-90% rise width, in pixels, of the block's left edge, averaged over its rows."""
    rows, columns = _block(width, height)
    left = columns.start
    profile = luma(rgb[rows, left - EDGE_REACH : left + EDGE_REACH].astype(np.float32)).mean(axis=0)
    low, high = profile[:EDGE_TAIL].mean(), profile[-EDGE_TAIL:].mean()
    scaled = (profile - low) / (high - low)
    return float(_crossing(scaled, RISE_HIGH) - _crossing(scaled, RISE_LOW))


def sanity(width: int, height: int, dpi: int) -> list[str]:
    noisy = make_print(width, height)
    flat = _flat_patch(width, height)
    before = float(luma(noisy[flat].astype(np.float32)).std())
    denoised = noisy.copy()
    apply_denoise(denoised, STAGES["all"], Event())
    after = float(luma(denoised[flat].astype(np.float32)).std())
    clean = make_print(width, height, noisy=False)
    sharp = clean.copy()
    apply_sharpen(sharp, STAGES["sharpen"], float(dpi), Event())
    return [
        f"flat-patch luma noise std: {before:.2f} -> {after:.2f} (denoise 50/50)",
        f"edge 10-90% width px: {edge_width(clean, width, height):.2f} -> "
        f"{edge_width(sharp, width, height):.2f} (sharpen 50)",
    ]


def median_seconds(run: Callable[[np.ndarray], None], image: np.ndarray, runs: int) -> float:
    times = []
    for _ in range(runs):
        work = image.copy()
        start = time.perf_counter()
        run(work)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def stage_runner(detail: PhotoDetail, dpi: int) -> Callable[[np.ndarray], None]:
    def run(pixels: np.ndarray) -> None:
        apply_denoise(pixels, detail, Event())
        apply_sharpen(pixels, detail, float(dpi), Event())

    return run


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def bench_size(label: str, inches: tuple[int, int, int], runs: int, default_threads: int) -> None:
    short, long, dpi = inches
    width, height = short * dpi, long * dpi
    image = make_print(width, height)
    megapixels = width * height / MEGAPIXEL
    print(f"\n{label}: {short}x{long} in at {dpi} dpi, {width}x{height}, {megapixels:.2f} MP")
    print(f"{'stage':8} {'1 thread s':>11} {'s/MP':>7} {'default s':>10} {'s/MP':>7}")
    for name, detail in STAGES.items():
        runner = stage_runner(detail, dpi)
        cv2.setNumThreads(1)
        one = median_seconds(runner, image, runs)
        cv2.setNumThreads(default_threads)
        many = median_seconds(runner, image, runs)
        print(f"{name:8} {one:11.3f} {one / megapixels:7.3f} {many:10.3f} {many / megapixels:7.3f}")
    del image
    for line in sanity(width, height, dpi):
        print(f"  {line}")


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=positive_int, default=DEFAULT_RUNS)
    parser.add_argument("--sizes", nargs="+", choices=sorted(INCH_SIZES), default=list(INCH_SIZES))
    args = parser.parse_args()
    default_threads = cv2.getNumThreads()
    print(f"OpenCV {cv2.__version__}; CPU {cpu_model()}; default threads {default_threads}")
    print(f"median of {args.runs} runs; stage strengths are 50; synthetic print, seed {SEED}")
    for key in args.sizes:
        bench_size(key, INCH_SIZES[key], args.runs, default_threads)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / KIB
    print(f"\npeak RSS of the whole run: {peak:.0f} MiB (includes the synthetic print)")


if __name__ == "__main__":
    main()
