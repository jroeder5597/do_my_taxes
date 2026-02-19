FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flyfield_service.py .

EXPOSE 5001

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "flyfield_service:app"]
