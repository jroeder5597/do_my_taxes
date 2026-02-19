"""
Tesseract OCR Service - Flask REST API
Provides OCR capabilities via HTTP endpoints
"""

import base64
import io
import logging
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify
from PIL import Image
import pytesseract

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
        'version': '1.0.0'
    })


@app.route('/ocr', methods=['POST'])
def ocr_image():
    """
    Perform OCR on an image.
    
    Request body (JSON):
    {
        "image": "base64_encoded_image_data",
        "lang": "eng" (optional, default "eng")
    }
    
    Or (multipart/form-data):
    - file: The image file
    """
    try:
        image_data = None
        
        if request.is_json:
            data = request.get_json()
            if not data or 'image' not in data:
                return jsonify({'error': 'No image data provided'}), 400
            
            image_data = base64.b64decode(data['image'])
            lang = data.get('lang', 'eng')
        elif 'file' in request.files:
            image_data = request.files['file'].read()
            lang = request.form.get('lang', 'eng')
        else:
            return jsonify({'error': 'No file provided'}), 400
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            tmp_file.write(image_data)
            tmp_path = tmp_file.name
        
        try:
            image = Image.open(tmp_path)
            
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            text = pytesseract.image_to_string(
                image,
                lang=lang,
            )
            
            return jsonify({
                'success': True,
                'text': text.strip(),
            })
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ocr/data', methods=['POST'])
def ocr_with_data():
    """
    Perform OCR with detailed data (bounding boxes, confidence, etc).
    
    Request body (JSON):
    {
        "image": "base64_encoded_image_data",
        "lang": "eng" (optional, default "eng")
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'image' not in data:
            return jsonify({'error': 'No image data provided'}), 400
        
        image_data = base64.b64decode(data['image'])
        lang = data.get('lang', 'eng')
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            tmp_file.write(image_data)
            tmp_path = tmp_file.name
        
        try:
            image = Image.open(tmp_path)
            
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            ocr_data = pytesseract.image_to_data(
                image,
                lang=lang,
                output_type=pytesseract.Output.DICT,
            )
            
            regions = []
            for i, text in enumerate(ocr_data.get("text", [])):
                if text.strip():
                    regions.append({
                        "text": text,
                        "left": ocr_data["left"][i],
                        "top": ocr_data["top"][i],
                        "width": ocr_data["width"][i],
                        "height": ocr_data["height"][i],
                        "confidence": int(ocr_data["conf"][i]) if ocr_data["conf"][i] != "-1" else 0,
                    })
            
            return jsonify({
                'success': True,
                'regions': regions,
            })
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"OCR with data failed: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting Tesseract OCR Service...")
    app.run(host='0.0.0.0', port=5002, debug=False)
