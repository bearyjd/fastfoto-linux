# Vendored models

- `face_detection_yunet_2023mar.onnx` - YuNet face detector, from OpenCV Zoo:
  https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
  (232589 bytes, sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`).
  MIT licence, Copyright (c) 2020 Shiqi Yu - see `LICENSE-YuNet`.

The loader (`fastfoto_linux.enhance.faces`) refuses a file whose sha256 differs. Models are never
downloaded at runtime.
