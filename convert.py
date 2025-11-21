from ultralytics import YOLO

model = YOLO("yolov8m-face-lindevs.pt")
model.export(format="onnx", opset=12, dynamic=False)
