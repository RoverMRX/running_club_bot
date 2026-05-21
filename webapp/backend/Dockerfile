FROM python:3.12-slim
WORKDIR /app
# Копируем модели и БД бота
COPY models.py .
COPY database.py .
# Копируем бэкенд
COPY webapp/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY webapp/backend/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
