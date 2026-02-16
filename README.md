# Tax Document Processor

A Python-based system to OCR tax documents (W-2, 1099-INT, 1099-DIV), extract structured data using a local LLM (Ollama), and provide assistance with tax filing.

## Features

- **OCR Processing**: Extract text from PDFs (digital and scanned) and images using Tesseract OCR via Podman container
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

2. **Podman**: [Download](https://podman.io/getting-started/installation)
   - Used for containerized Tesseract OCR service
   - No local Tesseract installation needed

3. **Ollama**: [Download](https://ollama.ai)
   - Pull the extraction model: `ollama pull qwen3:8b` (or your preferred model)

4. **Qdrant** (optional, for semantic search) - Will be started via CLI in step 4 below

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

4. **Build and start the OCR and Qdrant services:**
   ```bash
   # Build the OCR container image
   python -m src.cli build-ocr
   
   # Start the OCR service
   python -m src.cli start-ocr
   
   # Start the Qdrant service (for semantic search)
   python -m src.cli start-qdrant
   ```

5. Verify installations:
   ```bash
   python -m src.cli check-ocr
   python -m src.cli check-llm
   python -m src.cli check-qdrant
   ```

## Usage

### Process Tax Documents

Process all documents in a directory for a tax year:

```bash
python -m src.cli process --year 2025 --input ./data/raw_documents/
```

Process a single file:

```bash
python -m src.cli process --year 2025 --input ./w2_2025.pdf
```

### List Processed Documents

```bash
# List all documents
python -m src.cli list

# List for specific year
python -m src.cli list --year 2025

# Filter by type
python -m src.cli list --year 2025 --type W2
```

### View Tax Summary

```bash
python -m src.cli summary --year 2025
```

### Search Documents

```bash
python -m src.cli query --year 2025 --query "wages from employer"
```

### Export Data

```bash
# Export as JSON
python -m src.cli export --year 2025 --format json

# Export as CSV
python -m src.cli export --year 2025 --format csv
```

### Interactive Tax Assistant

```bash
python -m src.cli assist --year 2025
```

The assistant provides:
- Interactive Q&A about your tax documents
- Screen capture and analysis for TaxAct assistance
- Guidance on where to enter values in tax software
- Explanations of tax form fields
- **Up-to-date tax filing information** (when guidance is loaded)

#### Tax Guidance (Automatic)

Place tax instruction PDFs in the guidance directories:

```
data/
├── federal/       # IRS Form 1040 Instructions
├── ca/            # California Form 540 Instructions  
├── az/            # Arizona Form 140 Instructions
└── raw_documents/ # Your tax documents (W-2, 1099, etc.)
```

The assistant automatically loads guidance when you start it:
```bash
python -m src.cli assist --year 2025
```

To manually reload or test guidance:
```bash
# Load all guidance
python -m src.cli load-all-guidance --year 2025

# Search guidance
python -m src.cli search-guidance --year 2025 --jurisdiction ca "standard deduction"
```

The assistant will automatically retrieve relevant guidance when answering questions about federal, California, or Arizona taxes.

### OCR Service Management

Manage the containerized OCR service:

```bash
# Check OCR service status
python -m src.cli check-ocr

# Build the OCR Podman image
python -m src.cli build-ocr

# Start the OCR container
python -m src.cli start-ocr

# Stop the OCR container
python -m src.cli stop-ocr
```

### Qdrant Service Management

Manage the Qdrant vector database container:

```bash
# Check Qdrant service status
python -m src.cli check-qdrant

# Start the Qdrant container
python -m src.cli start-qdrant

# Stop the Qdrant container
python -m src.cli stop-qdrant
```

## Project Structure

```
do_my_taxes/
├── config/
│   ├── settings.yaml        # Main configuration
│   └── tax_schemas.yaml     # Tax form field definitions
├── containers/
│   └── tesseract-ocr/       # Containerized OCR service
│       ├── Dockerfile       # Podman image definition
│       ├── ocr_service.py   # Flask REST API for OCR
│       └── requirements.txt # Container dependencies
├── src/
│   ├── ocr/                 # OCR processing modules
│   │   ├── pdf_processor.py # PDF text extraction
│   │   ├── image_ocr.py     # Tesseract OCR via container
│   │   ├── ocr_client.py    # Client for OCR service
│   │   ├── docker_manager.py # Podman container management
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
│   │   ├── config.py        # Configuration loader
│   │   ├── logger.py
│   │   └── file_utils.py
│   ├── cli.py               # Command-line interface
│   └── main.py              # Entry point
├── data/
│   ├── raw_documents/       # Place tax documents here (W-2, 1099, etc.)
│   ├── federal/             # IRS tax instructions (PDF)
│   ├── ca/                  # California tax instructions (PDF)
│   ├── az/                  # Arizona tax instructions (PDF)
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
    model: "qwen3:8b"  # Your Ollama model for data extraction

ocr:
  service_url: "http://127.0.0.1:5000"  # OCR container service URL
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

### OCR Service not responding

If using the containerized OCR service:

```bash
# Check if the container is running
podman ps | grep tesseract-ocr-service

# Check container logs
podman logs tesseract-ocr-service

# Restart the container
python -m src.cli stop-ocr
python -m src.cli start-ocr

# Test the service health
curl http://localhost:5000/health
```

### Podman not found

```bash
# Install Podman
# Windows: Download from https://podman.io/getting-started/installation
# macOS: brew install podman
# Linux: sudo apt-get install podman

# Verify installation
podman --version
```

### Ollama connection failed

```bash
# Make sure Ollama is running
ollama serve

# Check available models
ollama list

# Pull extraction model if needed
ollama pull qwen3:8b
```

### PDF to image conversion fails

The OCR container includes poppler. No additional installation needed.

### Qdrant connection failed

```bash
# Start Qdrant with Podman
python -m src.cli start-qdrant

# Or manually with Docker/Podman
docker run -p 6333:6333 qdrant/qdrant
# or
podman run -d -p 127.0.0.1:6333:6333 --name qdrant-tax-service qdrant/qdrant:latest
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
