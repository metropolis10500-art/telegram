FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements ПЕРВЫМ (для кеширования)
COPY requirements.txt .

# Обновляем pip и ставим зависимости
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
    aiogram==3.13.1 \
    aiosqlite==0.20.0 \
    python-dotenv==1.0.1 \
    yoomoney

# Копируем код
COPY . .

CMD ["python", "bot.py"]
