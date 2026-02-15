# Tax Document Processor

A Python-based system to OCR tax documents (W-2, 1099-INT, 1099-DIV), extract structured data using a local LLM (Ollama), and provide assistance with tax filing.

## Features

- **OCR Processing**: Extract text from PDFs (digital and scanned) and images
- **LLM Data Extraction**: Use local Ollama LLM to extract structured data from tax forms
- **Hybrid Storage**: SQLite for structured data + Qdrant for semantic search
- **Tax Filing Assistant**: Interactive assistant to help with TaxAct and tax filing
- **Screen Reading**: Capture and analyze TaxAct screens for real-time assistance

## Supported Tax Forms

- **W-2**: Wage and Tax Statement
- **1099-INT**: Interest Income
- **1099-DIV**: Dividends and Distributions

## Prerequisites

### Required Software

1. **Python 3.10+**

2. **Tesseract OCR** (choose one option):

   **Option A: Containerized OCR Service (Recommended)**
   - Docker installed and running
   - No local Tesseract installation needed
   - Provides consistent OCR environment with all dependencies

   **Option B: Local Tesseract Installation**
   - [Installation Guide](https://github.com/tesseract-ocr/tesseract)
   - Windows: Download from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
   - **Poppler** (for PDF processing on Windows):
     - Download from [poppler-windows](https://github.com/oschwartz10612/poppler-windows)
     - Add to PATH

3. **Ollama**: [Download](https://ollama.ai)
   - Pull the model: `ollama pull gpt-oss:20b` (or your preferred model)

4. **Qdrant** (optional, for semantic search):
   ```bash
   docker run -p 6333:6333 qdrant/qdrant
   ```

### Python Dependencies

```bash
pip install -r requirements.txt
```

## Installation

1. Clone or download this project
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Edit `config/settings.yaml` with your configuration:
   - Set `llm.ollama.base_url` to your Ollama server address
   - Set `storage.qdrant.host` to your Qdrant server address
   - Configure other settings as needed

4. **Start the OCR Service** (choose one option):

   **Option A: Containerized OCR (Recommended)**
   ```bash
   # Build the OCR container
   docker build -t tesseract-ocr-service ./containers/tesseract-ocr/

   # Run the OCR service
   docker run -d -p 5000:5000 --name ocr-service tesseract-ocr-service

   # Update ocr.service_url in config/settings.yaml
   # ocr.service_url: "http://localhost:5000"
   ```

   **Option B: Local Tesseract**
   - Install Tesseract OCR locally (see Prerequisites)
   - Leave `ocr.service_url` set to `null` in config/settings.yaml

5. Verify installations:
   ```bash
   python -m src.main check-llm
   python -m src.main check-qdrant
   ```

## Usage

### Process Tax Documents

Process all documents in a directory for a tax year:

```bash
python -m src.main process --year 2025 --input ./data/raw_documents/
```

Process a single file:

```bash
python -m src.main process --year 2025 --input ./w2_2025.pdf
```

### List Processed Documents

```bash
# List all documents
python -m src.main list

# List for specific year
python -m src.main list --year 2025

# Filter by type
python -m src.main list --year 2025 --type W2
```

### View Tax Summary

```bash
python -m src.main summary --year 2025
```

### Search Documents

```bash
python -m src.main query --year 2025 --query "wages from employer"
```

### Export Data

```bash
# Export as JSON
python -m src.main export --year 2025 --format json

# Export as CSV
python -m src.main export --year 2025 --format csv
```

### Interactive Tax Assistant

```bash
python -m src.main assist --year 2025
```

The assistant provides:
- Interactive Q&A about your tax documents
- Screen capture and analysis for TaxAct assistance
- Guidance on where to enter values in tax software
- Explanations of tax form fields

### OCR Service Management

Manage the containerized OCR service:

```bash
# Check OCR service status
python -m src.main check-ocr

# Build the OCR Docker image
python -m src.main build-ocr

# Start the OCR container
python -m src.main start-ocr

# Stop the OCR container
python -m src.main stop-ocr
```

## Project Structure

```
do_my_taxes/
├── config/
│   ├── settings.yaml        # Main configuration
│   └── tax_schemas.yaml     # Tax form field definitions
├── containers/
│   └── tesseract-ocr/       # Containerized OCR service
│       ├── Dockerfile       # Docker image definition
│       └── ocr_service.py   # Flask REST API for OCR
├── src/
│   ├── ocr/                 # OCR processing modules
│   │   ├── pdf_processor.py
│   │   ├── image_ocr.py
│   │   ├── ocr_client.py    # Client for OCR service
│   │   └── document_classifier.py
│   ├── extraction/          # LLM extraction modules
│   │   ├── llm_extractor.py
│   │   ├── prompts.py
│   │   └── validators.py
│   ├── storage/             # Database modules
│   │   ├── sqlite_handler.py
│   │   ├── qdrant_handler.py
│   │   └── models.py
│   ├── assistant/           # Tax filing assistant
│   │   ├── tax_assistant.py
│   │   └── screen_reader.py
│   ├── utils/               # Utilities
│   │   ├── logger.py
│   │   └── file_utils.py
│   ├── cli.py               # Command-line interface
│   └── main.py              # Entry point
├── data/
│   ├── raw_documents/       # Place tax documents here
│   ├── processed/           # Processed documents
│   └── exports/             # Exported data
├── db/
│   └── taxes.db             # SQLite database
├── logs/                    # Application logs
├── plans/                   # Architecture documentation
├── tests/                   # Unit tests
├── requirements.txt
└── README.md
```

## Configuration

Edit `config/settings.yaml` to customize:

```yaml
llm:
  ollama:
    model: "gpt-oss:20b"  # Your Ollama model

ocr:
  service_url: "http://localhost:5000"  # Containerized OCR service (set to null for local Tesseract)
  languages: ["eng"]
  dpi: 300
    
storage:
  qdrant:
    host: "localhost"
    port: 6333
```

## OCR Service API

The containerized OCR service provides a REST API with the following endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/version` | GET | Get Tesseract version |
| `/languages` | GET | List available languages |
| `/ocr/image` | POST | OCR on base64-encoded image |
| `/ocr/pdf` | POST | OCR on base64-encoded PDF |
| `/ocr/file` | POST | OCR on uploaded file (multipart) |
| `/ocr/batch` | POST | OCR on multiple files |

Example usage:
```bash
# Check service health
curl http://localhost:5000/health

# OCR an image file
curl -X POST http://localhost:5000/ocr/file \
  -F "file=@document.png" \
  -F "language=eng"
```

## Security Notes

- **Sensitive Data**: Tax documents contain SSNs, EINs, and financial data
  - Never commit database files to version control
  - Consider encrypting the SQLite database
  - The system uses local LLM (Ollama) to keep data private

- **File Storage**: 
  - Raw documents are stored locally
  - Consider encrypting sensitive files at rest

## Troubleshooting

### Tesseract not found

If using local Tesseract (not containerized):

```bash
# Windows: Add to PATH or set in config
# config/settings.yaml
ocr:
  tesseract_path: "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

### OCR Service not responding

If using the containerized OCR service:

```bash
# Check if the container is running
docker ps | grep ocr-service

# Check container logs
docker logs ocr-service

# Restart the container
docker restart ocr-service

# Test the service health
curl http://localhost:5000/health
```

### Ollama connection failed

```bash
# Make sure Ollama is running
ollama serve

# Check available models
ollama list
```

### PDF to image conversion fails

If using local Tesseract (not containerized):

```bash
# Install poppler (Windows)
# Download from https://github.com/oschwartz10612/poppler-windows
# Add bin/ directory to PATH
```

### Qdrant connection failed

```bash
# Start Qdrant with Docker
docker run -p 6333:6333 qdrant/qdrant
```

## Development

### Run Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black src/
isort src/
```

### Type Checking

```bash
mypy src/
```

## License

This project is for personal use. Consult a tax professional for actual tax advice.

## Contributing

This is a personal project, but suggestions and improvements are welcome!

## Disclaimer

This tool is for educational and personal organization purposes only. It does not provide tax advice. Always consult a qualified tax professional for tax-related decisions. The accuracy of OCR and LLM extraction cannot be guaranteed - always verify extracted values against your original documents.