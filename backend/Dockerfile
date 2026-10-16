FROM python:3.12-slim
# M3c: tesseract-ocr(+vie) + poppler-utils (pdftoppm) cho OCR PDF scan / ảnh khi nạp tài liệu
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
    tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
