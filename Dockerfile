FROM python:3.11-slim

RUN apt-get update &&     apt-get install -y --no-install-recommends ffmpeg gcc &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fetch the YuNet face-detection model used by Smart Reframe (~230KB). Done at
# build time so the model ships in the image without committing a binary blob.
RUN mkdir -p models && python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx','models/face_detection_yunet_2023mar.onnx')"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
