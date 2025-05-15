# Базовый образ с Python
FROM python:3.10-slim

# Установка зависимостей из setup.sh
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-kaz \
    libmagic-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Копирование файлов
COPY requirements.txt .
COPY .env .
COPY . .

# Установка Python-зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Укажи здесь точку входа или команду запуска, например:
# CMD ["python", "main.py"]
