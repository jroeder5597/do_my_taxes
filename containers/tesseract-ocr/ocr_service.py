"""
Tesseract OCR REST API Service
Runs inside a container and provides OCR via HTTP endpoints.
"""

import base64
import io
import os
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes

app = Flask(__name__)

# Configuration
TESSERACT_LANGUAGES = os.environ.get("TESSERACT_LANGUAGES", "eng")
DEFAULT_DPI = int(os.environ.get("DEFAULT_DPI", "300"))


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "tesseract-ocr",
        "version": "1.0.0"
    })


@app.route("/ocr/image", methods=["POST"])
def ocr_image():
    """
    Perform OCR on an image.
    
    Request body (JSON):
    {
        "image": "base64-encoded image data",
        "language": "eng" (optional),
        "dpi": 300 (optional)
    }
    
    Returns:
    {
        "text": "extracted text",
        "confidence": {
            "average": 85.5,
            "min": 60,
            "max": 99,
            "word_count": 150
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data or "image" not in data:
            return jsonify({"error": "No image data provided"}), 400
        
        # Decode base64 image
        image_data = base64.b64decode(data["image"])
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Get options
        language = data.get("language", TESSERACT_LANGUAGES)
        dpi = data.get("dpi", DEFAULT_DPI)
        
        # Perform OCR
        text = pytesseract.image_to_string(
            image,
            lang=language,
            config=f"--dpi {dpi}"
        )
        
        # Get confidence data
        confidence_data = get_confidence_data(image, language)
        
        return jsonify({
            "text": text.strip(),
            "confidence": confidence_data
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ocr/pdf", methods=["POST"])
def ocr_pdf():
    """
    Perform OCR on a PDF file.
    
    Request body (JSON):
    {
        "pdf": "base64-encoded PDF data",
        "language": "eng" (optional),
        "dpi": 300 (optional)
    }
    
    Returns:
    {
        "pages": [
            {"page": 1, "text": "..."},
            {"page": 2, "text": "..."}
        ],
        "full_text": "combined text from all pages",
        "page_count": 2
    }
    """
    try:
        data = request.get_json()
        
        if not data or "pdf" not in data:
            return jsonify({"error": "No PDF data provided"}), 400
        
        # Decode base64 PDF
        pdf_data = base64.b64decode(data["pdf"])
        
        # Get options
        language = data.get("language", TESSERACT_LANGUAGES)
        dpi = data.get("dpi", DEFAULT_DPI)
        
        # Convert PDF to images
        images = convert_from_bytes(pdf_data, dpi=dpi)
        
        pages = []
        all_text = []
        
        for page_num, image in enumerate(images, 1):
            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            # Perform OCR
            page_text = pytesseract.image_to_string(
                image,
                lang=language,
                config=f"--dpi {dpi}"
            )
            
            pages.append({
                "page": page_num,
                "text": page_text.strip()
            })
            all_text.append(f"--- Page {page_num} ---\n{page_text.strip()}")
        
        return jsonify({
            "pages": pages,
            "full_text": "\n\n".join(all_text),
            "page_count": len(pages)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ocr/file", methods=["POST"])
def ocr_file():
    """
    Perform OCR on an uploaded file (image or PDF).
    
    Request: multipart/form-data with 'file' field
    
    Returns:
    {
        "text": "extracted text",
        "filename": "original filename",
        "file_type": "pdf" or "image"
    }
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        filename = file.filename
        
        # Get options from form data
        language = request.form.get("language", TESSERACT_LANGUAGES)
        dpi = int(request.form.get("dpi", DEFAULT_DPI))
        
        # Read file content
        file_data = file.read()
        
        # Determine file type
        suffix = Path(filename).suffix.lower()
        
        if suffix == ".pdf":
            # Process PDF
            images = convert_from_bytes(file_data, dpi=dpi)
            
            all_text = []
            for page_num, image in enumerate(images, 1):
                if image.mode != "RGB":
                    image = image.convert("RGB")
                
                page_text = pytesseract.image_to_string(
                    image,
                    lang=language,
                    config=f"--dpi {dpi}"
                )
                all_text.append(f"--- Page {page_num} ---\n{page_text.strip()}")
            
            return jsonify({
                "text": "\n\n".join(all_text),
                "filename": filename,
                "file_type": "pdf"
            })
        
        else:
            # Process as image
            image = Image.open(io.BytesIO(file_data))
            
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            text = pytesseract.image_to_string(
                image,
                lang=language,
                config=f"--dpi {dpi}"
            )
            
            return jsonify({
                "text": text.strip(),
                "filename": filename,
                "file_type": "image"
            })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ocr/batch", methods=["POST"])
def ocr_batch():
    """
    Perform OCR on multiple files.
    
    Request body (JSON):
    {
        "files": [
            {"name": "file1.pdf", "data": "base64-encoded data"},
            {"name": "file2.png", "data": "base64-encoded data"}
        ],
        "language": "eng" (optional),
        "dpi": 300 (optional)
    }
    
    Returns:
    {
        "results": [
            {"name": "file1.pdf", "text": "...", "success": true},
            {"name": "file2.png", "text": "...", "success": true}
        ]
    }
    """
    try:
        data = request.get_json()
        
        if not data or "files" not in data:
            return jsonify({"error": "No files provided"}), 400
        
        language = data.get("language", TESSERACT_LANGUAGES)
        dpi = data.get("dpi", DEFAULT_DPI)
        
        results = []
        
        for file_info in data["files"]:
            try:
                file_data = base64.b64decode(file_info["data"])
                filename = file_info["name"]
                suffix = Path(filename).suffix.lower()
                
                if suffix == ".pdf":
                    images = convert_from_bytes(file_data, dpi=dpi)
                    all_text = []
                    
                    for page_num, image in enumerate(images, 1):
                        if image.mode != "RGB":
                            image = image.convert("RGB")
                        
                        page_text = pytesseract.image_to_string(
                            image,
                            lang=language,
                            config=f"--dpi {dpi}"
                        )
                        all_text.append(page_text.strip())
                    
                    text = "\n\n".join(all_text)
                else:
                    image = Image.open(io.BytesIO(file_data))
                    
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                    
                    text = pytesseract.image_to_string(
                        image,
                        lang=language,
                        config=f"--dpi {dpi}"
                    )
                
                results.append({
                    "name": filename,
                    "text": text.strip(),
                    "success": True
                })
            
            except Exception as e:
                results.append({
                    "name": file_info.get("name", "unknown"),
                    "error": str(e),
                    "success": False
                })
        
        return jsonify({"results": results})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/languages", methods=["GET"])
def list_languages():
    """List available Tesseract languages."""
    try:
        langs = pytesseract.get_languages()
        return jsonify({
            "languages": langs,
            "default": TESSERACT_LANGUAGES
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/version", methods=["GET"])
def version():
    """Get Tesseract version."""
    try:
        version = pytesseract.get_tesseract_version()
        return jsonify({
            "tesseract_version": str(version)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_confidence_data(image: Image.Image, language: str) -> dict:
    """Get OCR confidence statistics for an image."""
    try:
        data = pytesseract.image_to_data(
            image,
            lang=language,
            output_type=pytesseract.Output.DICT
        )
        
        confidences = [int(c) for c in data.get("conf", []) if c != "-1"]
        
        if not confidences:
            return {"average": 0, "min": 0, "max": 0, "word_count": 0}
        
        return {
            "average": round(sum(confidences) / len(confidences), 2),
            "min": min(confidences),
            "max": max(confidences),
            "word_count": len(confidences)
        }
    except Exception:
        return {"average": 0, "min": 0, "max": 0, "word_count": 0}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)