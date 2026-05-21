FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir \
    aiogram==3.10.0 \
    sqlalchemy==2.0.25 \
    aiosqlite==0.19.0 \
    aiohttp~=3.9.0 \
    aiohttp-socks==0.8.0 \
    apscheduler==3.10.4 \
    python-dotenv==1.0.0 \
    "aiohttp[socks]"
COPY . .
CMD ["python", "bot.py"]
