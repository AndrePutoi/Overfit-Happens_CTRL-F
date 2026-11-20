FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY tests ./tests
COPY pytest.ini .
ENV TAXONOMIA_PATH=/app/shared/taxonomia.json \
    DB_INIT_DIR=/app/db/init \
    MEDIA_DIR=/data/media \
    UPLOAD_DIR=/data/uploads
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
