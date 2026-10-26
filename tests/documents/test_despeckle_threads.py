"""Overlapping labellings share one pin of OpenCV's thread count."""

import threading

import cv2
import pytest

from fastfoto_linux.documents import despeckle


@pytest.fixture
def four_threads():
    previous = cv2.getNumThreads()
    cv2.setNumThreads(4)
    yield
    cv2.setNumThreads(previous)


def test_overlapping_pins_label_on_one_thread_and_restore_once(four_threads) -> None:
    a_in, b_in, a_out = threading.Event(), threading.Event(), threading.Event()
    seen: dict[str, list[int]] = {"a": [], "b": []}

    def first() -> None:
        with despeckle._one_thread():
            seen["a"].append(cv2.getNumThreads())
            a_in.set()
            assert b_in.wait(10)
        seen["a"].append(cv2.getNumThreads())  # after A left, B is still inside
        a_out.set()

    def second() -> None:
        assert a_in.wait(10)
        with despeckle._one_thread():
            b_in.set()
            seen["b"].append(cv2.getNumThreads())
            assert a_out.wait(10)
            seen["b"].append(cv2.getNumThreads())  # A has left: still one thread

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert seen["b"] == [1, 1]
    assert seen["a"][0] == 1
    assert cv2.getNumThreads() == 4  # restored, once, to what it was before either


def test_the_count_is_restored_after_nested_pins_and_a_failure(four_threads) -> None:
    with pytest.raises(RuntimeError), despeckle._one_thread():
        with despeckle._one_thread():
            assert cv2.getNumThreads() == 1
        assert cv2.getNumThreads() == 1
        raise RuntimeError("x")
    assert cv2.getNumThreads() == 4
