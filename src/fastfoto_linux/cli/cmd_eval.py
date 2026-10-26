"""``ffscan eval``: offline evaluation harnesses."""

import argparse

from fastfoto_linux.enhance.faces import FaceDetector


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    raise NotImplementedError


def make_detector() -> FaceDetector | None:
    raise NotImplementedError


def run(args: argparse.Namespace) -> int:
    raise NotImplementedError
