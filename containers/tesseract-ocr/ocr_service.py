"""
Tesseract OCR Service - Flask REST API
Provides OCR capabilities via HTTP endpoints
"""

import base64
import io
import logging
from pathlib import Path
from typing import Optional

from flask import Flask, request, jsonify
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
import tempfile
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'tesseract-ocr',
        'version': str(pytesseract.get_tesseract_version())
    })

@app.route('/version', methods=['GET'])
def get_version():
    """Get Tesseract version."""
    return jsonify({
        'version': str(pytesseract.get_tesseract_version()),
        'languages': pytesseract.get_languages()
    })

@app.route('/languages', methods=['GET'])
def get_languages():
    """Get available languages."""
    return jsonify({
        'languages': pytesseract.get_languages()
    })

def perform_ocr(image: Image.Image, language: str = 'eng') -> str:
    """
    Perform OCR on an image.
    
    Args:
        image: PIL Image object
        language: OCR language code
        
    Returns:
        Extracted text
    """
    # Convert to RGB if necessary
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Perform OCR
    text = pytesseract.image_to_string(
        image,
        lang=language,
        config='--psm 6'  # Assume a single uniform block of text
    )
    
    return text.strip()

@app.route('/ocr/image', methods=['POST'])
def ocr_image():
    """
    OCR on base64-encoded image.
    
    Request body:
    {
        "image": "base64_encoded_image_data",
        "language": "eng" (optional)
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'image' not in data:
            return jsonify({'error': 'No image data provided'}), 400
        
        # Decode base64 image
        image_data = base64.b64decode(data['image'])
        image = Image.open(io.BytesIO(image_data))
        
        # Get language (default to eng)
        language = data.get('language', 'eng')
        
        # Perform OCR
        text = perform_ocr(image, language)
        
        return jsonify({
            'success': True,
            'text': text,
            'language': language
        })
        
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/ocr/pdf', methods=['POST'])
def ocr_pdf():
    """
    OCR on base64-encoded PDF.
    
    Request body:
    {
        "pdf": "base64_encoded_pdf_data",
        "language": "eng" (optional),
        "dpi": 300 (optional)
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'pdf' not in data:
            return jsonify({'error': 'No PDF data provided'}), 400
        
        # Decode base64 PDF
        pdf_data = base64.b64decode(data['pdf'])
        
        # Get options
        language = data.get('language', 'eng')
        dpi = data.get('dpi', 300)
        
        # Save PDF to temp file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            tmp_path = tmp_file.name
        
        try:
            # Convert PDF to images
            images = convert_from_path(tmp_path, dpi=dpi)
            
            # OCR each page
            text_parts = []
            for i, image in enumerate(images, 1):
                page_text = perform_ocr(image, language)
                text_parts.append(f"--- Page {i} ---\n{page_text}")
            
            full_text = "\n\n".join(text_parts)
            
            return jsonify({
                'success': True,
                'text': full_text,
                'pages': len(images),
                'language': language
            })
            
        finally:
            # Clean up temp file
            os.unlink(tmp_path)
            
    except Exception as e:
        logger.error(f"PDF OCR failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/ocr/file', methods=['POST'])
def ocr_file():
    """
    OCR on uploaded file (multipart/form-data).
    
    Form fields:
    - file: The image or PDF file
    - language: OCR language (optional, default: eng)
    - dpi: DPI for PDF conversion (optional, default: 300)
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        language = request.form.get('language', 'eng')
        dpi = int(request.form.get('dpi', 300))
        
        # Read file into memory
        file_data = file.read()
        
        # Check if PDF or image
        if file.filename.lower().endswith('.pdf'):
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_file.write(file_data)
                tmp_path = tmp_file.name
            
            try:
                # Convert PDF to images
                images = convert_from_path(tmp_path, dpi=dpi)
                
                # OCR each page
                text_parts = []
                for i, image in enumerate(images, 1):
                    page_text = perform_ocr(image, language)
                    text_parts.append(f"--- Page {i} ---\n{page_text}")
                
                full_text = "\n\n".join(text_parts)
                
                return jsonify({
                    'success': True,
                    'text': full_text,
                    'pages': len(images),
                    'language': language,
                    'filename': file.filename
                })
                
            finally:
                os.unlink(tmp_path)
        else:
            # Process as image
            image = Image.open(io.BytesIO(file_data))
            text = perform_ocr(image, language)
            
            return jsonify({
                'success': True,
                'text': text,
                'language': language,
                'filename': file.filename
            })
            
    except Exception as e:
        logger.error(f"File OCR failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/ocr/batch', methods=['POST'])
def ocr_batch():
    """
    OCR on multiple files.
    
    Request body (multipart/form-data):
    - files[]: Multiple files
    - language: OCR language (optional)
    """
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        language = request.form.get('language', 'eng')
        
        results = []
        for file in files:
            if file.filename:
                try:
                    file_data = file.read()
                    
                    if file.filename.lower().endswith('.pdf'):
                        # Handle PDF
                        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                            tmp_file.write(file_data)
                            tmp_path = tmp_file.name
                        
                        try:
                            images = convert_from_path(tmp_path, dpi=300)
                            text_parts = []
                            for i, image in enumerate(images, 1):
                                page_text = perform_ocr(image, language)
                                text_parts.append(f"--- Page {i} ---\n{page_text}")
                            text = "\n\n".join(text_parts)
                        finally:
                            os.unlink(tmp_path)
                    else:
                        # Handle image
                        image = Image.open(io.BytesIO(file_data))
                        text = perform_ocr(image, language)
                    
                    results.append({
                        'filename': file.filename,
                        'success': True,
                        'text': text
                    })
                    
                except Exception as e:
                    results.append({
                        'filename': file.filename,
                        'success': False,
                        'error': str(e)
                    })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(files),
            'successful': sum(1 for r in results if r['success'])
        })
            
    except Exception as e:
        logger.error(f"Batch OCR failed: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Tesseract OCR Service...")
    logger.info(f"Tesseract version: {pytesseract.get_tesseract_version()}")
    logger.info(f"Available languages: {pytesseract.get_languages()}")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
