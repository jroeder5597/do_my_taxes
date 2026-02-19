"""
Flyfield PDF Form Extraction Service - Flask REST API
Provides form field extraction capabilities via HTTP endpoints
"""

import base64
import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List

from flask import Flask, request, jsonify
import fitz  # PyMuPDF
import pdfplumber
from pypdf import PdfReader
import pandas as pd


KNOWN_BROKERAGES = [
    "CHARLES SCHWAB",
    "SCHWAB",
    "FIDELITY",
    "VANGUARD",
    "E*TRADE",
    "ETRADE",
    "TD AMERITRADE",
    "AMERITRADE",
    "ROBINHOOD",
    "INTERACTIVE BROKERS",
    "IBKR",
    "MERRILL LYNCH",
    "MERRILL",
    "MORGAN STANLEY",
    "GOLDMAN SACHS",
    "JPMORGAN",
    "JP MORGAN",
    "CHARLES SCHWAB & CO",
    "SCHWAB & CO",
    "SCHWAB ONE",
    "ALLY INVEST",
    "ALLY BANK",
    "TRADEKING",
    "SAXO BANK",
    "APEX CLEARING",
    "FIRSTCLEARING",
    "PERSHING",
    "NESTWISE",
    "BETTERMENT",
    "WEALTHFRONT",
    "ACORNS",
    "STASH",
    "SOFI",
    "WEBULL",
    "TIGER BROKERS",
    "MOOMOO",
]


KNOWN_BROKERAGE_KEYWORDS = [
    "SCHWAB",
    "FIDELITY",
    "VANGUARD",
    "ETRADE",
    "AMERITRADE",
    "ROBINHOOD",
    "INTERACTIVE BROKERS",
    "MERRILL",
    "MORGAN STANLEY",
    "GOLDMAN",
    "JPMORGAN",
    "ALLY",
    "TRADEKING",
    "APEX",
    "PERSHING",
    "NESTWISE",
    "BETTERMENT",
    "WEALTHFRONT",
    "ACORNS",
    "SOFI",
    "WEBULL",
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def extract_form_fields(pdf_path: str) -> Dict[str, Any]:
    """
    Extract form field values from a PDF using PyMuPDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Dictionary containing form field data
    """
    doc = fitz.open(pdf_path)
    fields = {}
    
    # Get form field widgets
    widget_types = {
        1: "Button",
        2: "CheckBox", 
        3: "RadioButton",
        4: "Text",
        5: "Choice",
        6: "Signature"
    }
    
    for page_num, page in enumerate(doc):
        widgets = page.widgets()
        for widget in widgets:
            field_name = widget.field_name
            if field_name:
                field_type = widget.field_type
                field_type_name = widget_types.get(field_type, "Unknown")
                
                # Get field value based on type
                if field_type == 4:  # Text field
                    value = widget.text
                elif field_type in (2, 3):  # CheckBox/RadioButton
                    value = widget.is_checked
                elif field_type == 5:  # Choice
                    value = widget.choice_value
                else:
                    value = str(widget)
                
                fields[field_name] = {
                    'value': value,
                    'type': field_type_name,
                    'page': page_num + 1
                }
    
    doc.close()
    return fields


def extract_text_with_coordinates(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract all text with bounding box coordinates.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        List of text items with position data
    """
    doc = fitz.open(pdf_path)
    text_items = []
    
    for page_num, page in enumerate(doc):
        text = page.get_text("dict")
        for block in text.get("blocks", []):
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_items.append({
                            'text': span.get("text", "").strip(),
                            'x0': span.get("bbox", [0, 0, 0, 0])[0],
                            'y0': span.get("bbox", [0, 0, 0, 0])[1],
                            'x1': span.get("bbox", [0, 0, 0, 0])[2],
                            'y1': span.get("bbox", [0, 0, 0, 0])[3],
                            'page': page_num + 1
                        })
    
    doc.close()
    return text_items


def extract_by_region(pdf_path: str, x0: float, y0: float, x1: float, y1: float, page: int = 1) -> str:
    """
    Extract text from a specific region of a PDF page.
    
    Args:
        pdf_path: Path to the PDF file
        x0, y0: Top-left corner coordinates
        x1, y1: Bottom-right corner coordinates
        page: Page number (1-indexed)
        
    Returns:
        Extracted text from the region
    """
    doc = fitz.open(pdf_path)
    
    if page > len(doc):
        doc.close()
        return ""
    
    target_page = doc[page - 1]
    rect = fitz.Rect(x0, y0, x1, y1)
    text = target_page.get_text("text", clip=rect)
    
    doc.close()
    return text.strip()


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'pdfplumber-tax-service',
        'version': '1.0.0'
    })


@app.route('/extract/fields', methods=['POST'])
def extract_fields():
    """
    Extract form field values from a PDF.
    
    Request body (JSON):
    {
        "pdf": "base64_encoded_pdf_data"
    }
    
    Or (multipart/form-data):
    - file: The PDF file
    """
    try:
        pdf_data = None
        temp_path = None
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            if not data or 'pdf' not in data:
                return jsonify({'error': 'No PDF data provided'}), 400
            pdf_data = base64.b64decode(data['pdf'])
        elif 'file' in request.files:
            pdf_data = request.files['file'].read()
        else:
            return jsonify({'error': 'No file provided'}), 400
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name
        
        try:
            fields = extract_form_fields(temp_path)
            
            return jsonify({
                'success': True,
                'fields': fields,
                'count': len(fields)
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/extract/text', methods=['POST'])
def extract_text():
    """
    Extract all text with coordinates from a PDF.
    
    Request body (JSON):
    {
        "pdf": "base64_encoded_pdf_data"
    }
    
    Or (multipart/form-data):
    - file: The PDF file
    """
    try:
        pdf_data = None
        temp_path = None
        
        if request.is_json:
            data = request.get_json()
            if not data or 'pdf' not in data:
                return jsonify({'error': 'No PDF data provided'}), 400
            pdf_data = base64.b64decode(data['pdf'])
        elif 'file' in request.files:
            pdf_data = request.files['file'].read()
        else:
            return jsonify({'error': 'No file provided'}), 400
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name
        
        try:
            text_items = extract_text_with_coordinates(temp_path)
            
            return jsonify({
                'success': True,
                'text_items': text_items,
                'count': len(text_items)
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/extract/region', methods=['POST'])
def extract_region():
    """
    Extract text from a specific region of a PDF page.
    
    Request body (JSON):
    {
        "pdf": "base64_encoded_pdf_data",
        "x0": 100,
        "y0": 100,
        "x1": 300,
        "y1": 200,
        "page": 1
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'pdf' not in data:
            return jsonify({'error': 'No PDF data provided'}), 400
        
        # Get region coordinates
        x0 = data.get('x0', 0)
        y0 = data.get('y0', 0)
        x1 = data.get('x1', 1000)
        y1 = data.get('y1', 1000)
        page = data.get('page', 1)
        
        pdf_data = base64.b64decode(data['pdf'])
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name
        
        try:
            text = extract_by_region(temp_path, x0, y0, x1, y1, page)
            
            return jsonify({
                'success': True,
                'text': text,
                'region': {
                    'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                    'page': page
                }
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"Region extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/extract/w2', methods=['POST'])
def extract_w2():
    """
    Extract W2 form data using pypdf form fields and pdfplumber.

    Request body (JSON):
    {
        "pdf": "base64_encoded_pdf_data",
        "format": "json" (optional, default "json"; also "csv" or "flat")
    }

    Returns extracted W2 fields with values.
    """
    try:
        data = request.get_json()

        if not data or 'pdf' not in data:
            return jsonify({'error': 'No PDF data provided'}), 400

        output_format = data.get('format', 'json')
        pdf_data = base64.b64decode(data['pdf'])

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name

        try:
            form_fields = _extract_pypdf_form_fields(temp_path)
            page_data = _extract_pdfplumber_data(temp_path)

            result = {
                'success': True,
                'form_fields': form_fields,
                'page_data': page_data,
            }

            if output_format == 'csv' and form_fields:
                df = pd.DataFrame([form_fields])
                result['csv'] = df.to_csv(index=False)
            elif output_format == 'flat':
                result['flat'] = {k: v for k, v in form_fields.items()}

            return jsonify(result)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        logger.error(f"W2 extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


def _extract_pypdf_form_fields(pdf_path: str) -> Dict[str, Any]:
    reader = PdfReader(pdf_path)
    fields = reader.get_form_text_fields()
    return fields or {}


def _extract_pdfplumber_data(pdf_path: str) -> Dict[str, Any]:
    results = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_data = {
                "text": page.extract_text(),
                "tables": [],
                "chars": []
            }

            tables = page.extract_tables()
            if tables:
                page_data["tables"] = tables

            chars = page.chars
            if chars:
                page_data["chars"] = chars

            results[f"page_{i+1}"] = page_data

    return results


def _extract_names_from_1099(text: str) -> tuple:
    """
    Dynamically extract payer and recipient names from 1099 forms.
    Uses text parsing with known brokerage names to identify the payer.
    """
    payer_name = None
    recipient_name = None
    
    lines = text.split('\n')
    for line in lines:
        if 'Name and Address' in line:
            continue
        
        has_recipient_name = bool(re.search(r'[A-Z][A-Z]+ [A-Z]+ [A-Z]+', line))
        has_brokerage = any(kw in line.upper() for kw in KNOWN_BROKERAGE_KEYWORDS)
        
        if has_recipient_name and has_brokerage:
            for keyword in KNOWN_BROKERAGE_KEYWORDS:
                if keyword in line.upper():
                    match = re.search(rf'([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s+([A-Z].*?{keyword}.*)', line, re.IGNORECASE)
                    if match:
                        recipient_name = match.group(1).strip()
                        payer_part = match.group(2).strip()
                        if 'CO' in payer_part.upper() or 'INC' in payer_part.upper():
                            payer_name = payer_part
                        else:
                            payer_name = f"{payer_part} CO., INC."
                        return payer_name, recipient_name
    
    for keyword in KNOWN_BROKERAGE_KEYWORDS:
        if keyword in text.upper():
            match = re.search(rf"([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s+([A-Z].*?{keyword}.*?)(?:\s+CO|\s+INC|\s+\d|\s*$)", text, re.IGNORECASE)
            if match:
                recipient_name = match.group(1).strip()
                payer_match = match.group(2).strip()
                if 'CO' not in payer_match.upper() and 'INC' not in payer_match.upper():
                    payer_name = f"{payer_match} CO., INC."
                else:
                    payer_name = payer_match
                return payer_name, recipient_name
    
    for keyword in KNOWN_BROKERAGE_KEYWORDS:
        if keyword in text.upper():
            match = re.search(rf"([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s*\n\s*([A-Z].*?{keyword})", text, re.IGNORECASE)
            if match:
                recipient_name = match.group(1).strip()
                payer_name = match.group(2).strip()
                if '&' in payer_name or 'CO' in payer_name.upper():
                    pass
                else:
                    payer_name = f"{payer_name} {keyword}"
                break
    
    if not payer_name:
        payer_section = re.search(r"Payer['\u2019]s Name and Address\s*\n(.+?)(?=\n[A-Z]|\n\d|\n\s*Tel|\n\s*Federal)", text, re.DOTALL)
        if payer_section:
            payer_text = payer_section.group(1).strip()
            payer_name = payer_text
    
    if not recipient_name:
        recipient_section = re.search(r"Recipient['\u2019]s Name and Address\s*\n(.+?)(?=\n[A-Z]|\n\d|\n\s*Taxpayer)", text, re.DOTALL)
        if recipient_section:
            recipient_text = recipient_section.group(1).strip()
            recipient_name = recipient_text
    
    if not recipient_name:
        name_match = re.search(r"([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s+\d", text)
        if name_match:
            recipient_name = name_match.group(1).strip()
    
    if not payer_name:
        for keyword in KNOWN_BROKERAGE_KEYWORDS:
            if keyword in text.upper():
                addr_match = re.search(rf"{keyword}.+?\d{{5}}", text, re.IGNORECASE)
                if addr_match:
                    payer_text = addr_match.group(0)
                    for kw in KNOWN_BROKERAGE_KEYWORDS:
                        if kw in payer_text.upper():
                            idx = payer_text.upper().find(kw)
                            payer_name = payer_text[idx:].strip()
                            break
                    break
    
    return payer_name, recipient_name
    
    for keyword in KNOWN_BROKERAGE_KEYWORDS:
        if keyword in text.upper():
            match = re.search(rf"([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s+([A-Z].*?{keyword})", text, re.IGNORECASE)
            if match:
                recipient_name = match.group(1).strip()
                payer_name = match.group(2).strip()
                if '&' in payer_name or 'CO' in payer_name.upper():
                    pass
                else:
                    payer_name = f"{payer_name} {keyword}"
                break
    
    if not payer_name:
        payer_section = re.search(r"Payer['\u2019]s Name and Address\s*\n(.+?)(?=\n[A-Z]|\n\d|\n\s*Tel|\n\s*Federal)", text, re.DOTALL)
        if payer_section:
            payer_text = payer_section.group(1).strip()
            payer_name = payer_text
    
    if not recipient_name:
        recipient_section = re.search(r"Recipient['\u2019]s Name and Address\s*\n(.+?)(?=\n[A-Z]|\n\d|\n\s*Taxpayer)", text, re.DOTALL)
        if recipient_section:
            recipient_text = recipient_section.group(1).strip()
            recipient_name = recipient_text
    
    if not recipient_name:
        name_match = re.search(r"([A-Z][A-Z]+ [A-Z]+ [A-Z]+)\s+\d", text)
        if name_match:
            recipient_name = name_match.group(1).strip()
    
    if not payer_name:
        for keyword in KNOWN_BROKERAGE_KEYWORDS:
            if keyword in text.upper():
                addr_match = re.search(rf"{keyword}.+?\d{{5}}", text, re.IGNORECASE)
                if addr_match:
                    payer_text = addr_match.group(0)
                    for kw in KNOWN_BROKERAGE_KEYWORDS:
                        if kw in payer_text.upper():
                            idx = payer_text.upper().find(kw)
                            payer_name = payer_text[idx:].strip()
                            break
                    break
    
    return payer_name, recipient_name


def _extract_1099_div_from_text(text: str) -> Dict[str, Any]:
    """Extract 1099-DIV data from PDF text."""
    data = {}
    
    payer_name, recipient_name = _extract_names_from_1099(text)
    data['payer_name'] = payer_name
    data['recipient_name'] = recipient_name
    
    ein_match = re.search(r"Federal ID Number:\s*(\d{2}-\d{7})", text)
    if ein_match:
        data['payer_ein'] = ein_match.group(1)
    
    ssn_match = re.search(r"Taxpayer ID Number:\s*(\*{6}\d{4})", text)
    if ssn_match:
        data['recipient_ssn'] = ssn_match.group(1)
    
    account_match = re.search(r"Account Number:\s*(\d+[\d-]*)", text)
    if account_match:
        data['account_number'] = account_match.group(1)
    
    box_patterns = [
        ('box_1a_total_ordinary_dividends', r"1a\s+Total Ordinary Dividends\s+\$\s*([\d,]+\.\d{2})"),
        ('box_1b_qualified_dividends', r"1b\s+Qualified Dividends\s+\$\s*([\d,]+\.\d{2})"),
        ('box_2a_capital_gain', r"2a\s+Total Capital Gain Distributions\s+\$\s*([\d,]+\.\d{2})"),
        ('box_3_nondividend_distributions', r"3\s+Nondividend Distributions\s+\$\s*([\d,]+\.\d{2})"),
        ('box_4_federal_withholding', r"4\s+Federal Income Tax Withheld\s+\$\s*([\d,]+\.\d{2})"),
        ('box_5_section_199a', r"5\s+Section 199A Dividends\s+\$\s*([\d,]+\.\d{2})"),
        ('box_6_investment_expenses', r"6\s+Investment Expenses\s+\$\s*([\d,]+\.\d{2})"),
        ('box_7_foreign_tax_paid', r"7\s+Foreign Tax Paid\s+\$\s*([\d,]+\.\d{2})"),
        ('box_12_exempt_interest_dividends', r"12\s+Exempt-Interest Dividends\s+\$\s*([\d,]+\.\d{2})"),
    ]
    
    for field, pattern in box_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                data[field] = float(match.group(1).replace(',', ''))
            except ValueError:
                data[field] = match.group(1)
    
    return data


def _extract_1099_int_from_text(text: str) -> Dict[str, Any]:
    """Extract 1099-INT data from PDF text."""
    data = {}
    
    payer_name, recipient_name = _extract_names_from_1099(text)
    data['payer_name'] = payer_name
    data['recipient_name'] = recipient_name
    
    ein_match = re.search(r"Federal ID Number:\s*(\d{2}-\d{7})", text)
    if ein_match:
        data['payer_ein'] = ein_match.group(1)
    
    ssn_match = re.search(r"Taxpayer ID Number:\s*(\*{6}\d{4})", text)
    if ssn_match:
        data['recipient_ssn'] = ssn_match.group(1)
    
    account_match = re.search(r"Account Number:\s*(\d+[\d-]*)", text)
    if account_match:
        data['account_number'] = account_match.group(1)
    
    box_patterns = [
        ('box_1_interest_income', r"1\s+Interest Income\s+\$\s*([\d,]+\.\d{2})"),
        ('box_3_treasury_obligations', r"3\s+Interest on U.S. Savings Bonds and Treasury Obligations\s+\$\s*([\d,]+\.\d{2})"),
        ('box_4_federal_withholding', r"4\s+Federal Income Tax Withheld\s+\$\s*([\d,]+\.\d{2})"),
        ('box_5_investment_expenses', r"5\s+Investment Expenses\s+\$\s*([\d,]+\.\d{2})"),
        ('box_6_foreign_tax_paid', r"6\s+Foreign Tax Paid\s+\$\s*([\d,]+\.\d{2})"),
        ('box_8_tax_exempt_interest', r"8\s+Tax-Exempt Interest\s+\$\s*([\d,]+\.\d{2})"),
    ]
    
    for field, pattern in box_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                data[field] = float(match.group(1).replace(',', ''))
            except ValueError:
                data[field] = match.group(1)
    
    return data


@app.route('/extract/1099_div', methods=['POST'])
def extract_1099_div():
    """Extract 1099-DIV form data from PDF text."""
    try:
        data = request.get_json()
        
        if not data or 'pdf' not in data:
            return jsonify({'error': 'No PDF data provided'}), 400
        
        pdf_data = base64.b64decode(data['pdf'])
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name
        
        try:
            page_data = _extract_pdfplumber_data(temp_path)
            
            div_text = ""
            for page_key in sorted(page_data.keys()):
                text = page_data[page_key].get('text', '')
                if ('1099-DIV' in text or 'Dividends and Distributions' in text) and 'Total Ordinary Dividends' in text:
                    div_text += text + "\n"
                    break
            
            if not div_text:
                for page_key in sorted(page_data.keys()):
                    text = page_data[page_key].get('text', '')
                    if '1099-DIV' in text or 'Dividends and Distributions' in text:
                        div_text += text + "\n"
            
            extracted = _extract_1099_div_from_text(div_text)
            
            return jsonify({
                'success': True,
                'data': extracted,
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
    
    except Exception as e:
        logger.error(f"1099-DIV extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/extract/1099_int', methods=['POST'])
def extract_1099_int():
    """Extract 1099-INT form data from PDF text."""
    try:
        data = request.get_json()
        
        if not data or 'pdf' not in data:
            return jsonify({'error': 'No PDF data provided'}), 400
        
        pdf_data = base64.b64decode(data['pdf'])
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_data)
            temp_path = tmp_file.name
        
        try:
            page_data = _extract_pdfplumber_data(temp_path)
            
            int_text = ""
            for page_key in sorted(page_data.keys()):
                text = page_data[page_key].get('text', '')
                if ('1099-INT' in text or 'Interest Income' in text) and 'Interest Income' in text and '$' in text:
                    int_text += text + "\n"
                    break
            
            if not int_text:
                for page_key in sorted(page_data.keys()):
                    text = page_data[page_key].get('text', '')
                    if '1099-INT' in text or 'Interest Income' in text:
                        int_text += text + "\n"
            
            extracted = _extract_1099_int_from_text(int_text)
            
            return jsonify({
                'success': True,
                'data': extracted,
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
    
    except Exception as e:
        logger.error(f"1099-INT extraction failed: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting Flyfield PDF Form Extraction Service...")
    app.run(host='0.0.0.0', port=5001, debug=False)
