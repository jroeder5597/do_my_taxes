# Tesseract OCR Service Container
# Provides a REST API for OCR processing

FROM python:3.11-slim

# Install Tesseract and dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    libgl1-mesa-glx \
    libglib2.0-0 \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    flask \
    pytesseract \
    pdf2image \
    pillow \
    gunicorn

# Create app directory
WORKDIR /app

# Copy the OCR service
COPY ocr_service.py .

# Create directories for file processing
RUN mkdir -p /tmp/input /tmp/output

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run the service
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "120", "ocr_service:app"]