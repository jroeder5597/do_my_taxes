"""
Flyfield-based PDF extraction for W2 forms.
Uses pypdf form fields and pdfplumber for reliable data capture.
"""

import base64
import requests
from typing import Optional, Dict, Any
from decimal import Decimal

FLYFIELD_URL = "http://localhost:5001"


class FlyfieldExtractor:
    """Extract W2 data using flyfield's pypdf + pdfplumber extraction."""

    def __init__(self, flyfield_url: str = FLYFIELD_URL):
        self.flyfield_url = flyfield_url

    def _call_w2_endpoint(self, pdf_b64: str, output_format: str = "json") -> Optional[Dict[str, Any]]:
        try:
            response = requests.post(
                f"{self.flyfield_url}/extract/w2",
                json={'pdf': pdf_b64, 'format': output_format},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def _extract_text(self, pdf_b64: str) -> str:
        try:
            response = requests.post(
                f"{self.flyfield_url}/extract/text",
                json={'pdf': pdf_b64},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                items = sorted(data.get('text_items', []), key=lambda x: x.get('y0', 0))
                return '\n'.join(item.get('text', '') for item in items)
        except Exception:
            pass
        return ""

    def extract_w2_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        with open(file_path, 'rb') as f:
            pdf_b64 = base64.b64encode(f.read()).decode()

        result = self._call_w2_endpoint(pdf_b64)
        if not result or not result.get('success'):
            return None

        form_fields = result.get('form_fields', {})
        page_data = result.get('page_data', {})

        if form_fields:
            return self._normalize_form_fields(form_fields)

        page_text = ""
        for page_key in sorted(page_data.keys()):
            text = page_data[page_key].get('text', '')
            if text:
                page_text += text + "\n"

        if page_text.strip():
            return self._parse_w2_text(page_text)

        return None

    def extract_w2_from_base64(self, pdf_b64: str) -> Optional[Dict[str, Any]]:
        result = self._call_w2_endpoint(pdf_b64)
        if not result or not result.get('success'):
            return None

        form_fields = result.get('form_fields', {})
        page_data = result.get('page_data', {})

        if form_fields:
            return self._normalize_form_fields(form_fields)

        page_text = ""
        for page_key in sorted(page_data.keys()):
            text = page_data[page_key].get('text', '')
            if text:
                page_text += text + "\n"

        if page_text.strip():
            return self._parse_w2_text(page_text)

        return None

    def _normalize_form_fields(self, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        import re

        field_mapping = {
            'wages': 'wages_tips_compensation',
            'box1': 'wages_tips_compensation',
            'box_1': 'wages_tips_compensation',
            'federal': 'federal_income_tax_withheld',
            'fed_tax': 'federal_income_tax_withheld',
            'box2': 'federal_income_tax_withheld',
            'box_2': 'federal_income_tax_withheld',
            'ss_wages': 'social_security_wages',
            'social_security_wages': 'social_security_wages',
            'box3': 'social_security_wages',
            'box_3': 'social_security_wages',
            'ss_tax': 'social_security_tax_withheld',
            'social_security_tax': 'social_security_tax_withheld',
            'box4': 'social_security_tax_withheld',
            'box_4': 'social_security_tax_withheld',
            'medicare_wages': 'medicare_wages',
            'box5': 'medicare_wages',
            'box_5': 'medicare_wages',
            'medicare_tax': 'medicare_tax_withheld',
            'box6': 'medicare_tax_withheld',
            'box_6': 'medicare_tax_withheld',
            'state_wages': 'state_wages_tips',
            'box16': 'state_wages_tips',
            'box_16': 'state_wages_tips',
            'state_tax': 'state_income_tax',
            'state_income_tax': 'state_income_tax',
            'box17': 'state_income_tax',
            'box_17': 'state_income_tax',
            'employer_name': 'employer_name',
            'employer_ein': 'employer_ein',
            'employee_name': 'employee_name',
            'employee_ssn': 'employee_ssn',
            'employer_address': 'employer_address',
            'employee_address': 'employee_address',
            'employer_state': 'employer_state',
        }

        data = {}
        for key, value in fields.items():
            if value is None or str(value).strip() == '':
                continue
            normalized_key = re.sub(r'[^a-z0-9_]', '_', key.lower()).strip('_')
            for pattern, target in field_mapping.items():
                if pattern in normalized_key:
                    data[target] = str(value).strip()
                    break
            else:
                data[normalized_key] = str(value).strip()

        return data if data else None

    def _parse_w2_text(self, text: str) -> Optional[Dict[str, Any]]:
        import re

        data = {}
        lines = text.split('\n')

        for i, line in enumerate(lines):
            if i + 1 >= len(lines):
                break
            next_line = lines[i + 1].strip()

            if re.match(r'^1\s*Wages.*2\s*Federal', line, re.IGNORECASE):
                amounts = re.findall(r'(\d[\d,]*\.\d{2})', next_line)
                if len(amounts) >= 2:
                    data['wages_tips_compensation'] = amounts[0].replace(',', '')
                    data['federal_income_tax_withheld'] = amounts[1].replace(',', '')
                break

        for i, line in enumerate(lines):
            if i + 1 >= len(lines):
                break
            next_line = lines[i + 1].strip()

            if re.match(r'^3\s*Social\s*security\s*wages.*4\s*Social', line, re.IGNORECASE):
                amounts = re.findall(r'(\d[\d,]*\.\d{2})', next_line)
                if len(amounts) >= 2:
                    data['social_security_wages'] = amounts[0].replace(',', '')
                    data['social_security_tax_withheld'] = amounts[1].replace(',', '')
                break

        for i, line in enumerate(lines):
            if i + 1 >= len(lines):
                break
            next_line = lines[i + 1].strip()

            if re.match(r'^5\s*Medicare\s*wages.*6\s*Medicare', line, re.IGNORECASE):
                amounts = re.findall(r'(\d[\d,]*\.\d{2})', next_line)
                if len(amounts) >= 2:
                    data['medicare_wages'] = amounts[0].replace(',', '')
                    data['medicare_tax_withheld'] = amounts[1].replace(',', '')
                break

        for i, line in enumerate(lines):
            if re.search(r'16\s*State\s*wages', line, re.IGNORECASE):
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
                combined = line + ' ' + next_line
                amounts = re.findall(r'(\d[\d,]*\.\d{2})', combined)
                if amounts:
                    data['state_wages_tips'] = amounts[-1].replace(',', '')
                break

        for i, line in enumerate(lines):
            if re.match(r'^17\s*State\s*income\s*tax', line, re.IGNORECASE):
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
                amounts = re.findall(r'(\d[\d,]*\.\d{2})', next_line)
                if amounts:
                    data['state_income_tax'] = amounts[0].replace(',', '')
                break

        for line in lines:
            ein_match = re.search(r'\d{2}-\d{7}', line)
            if ein_match:
                data['employer_ein'] = ein_match.group()
                break

        for line in lines:
            ssn_match = re.search(r'[X*]{3}-[X*]{2}-\d{4}|\d{3}-\d{2}-\d{4}', line)
            if ssn_match:
                data['employee_ssn'] = ssn_match.group()
                break

        for i, line in enumerate(lines):
            if re.search(r'Employer.*name.*address', line, re.IGNORECASE):
                for j in range(i + 1, min(i + 4, len(lines))):
                    candidate = lines[j].strip()
                    if candidate and re.match(r'^[A-Z][A-Z\s&.,]+$', candidate):
                        data['employer_name'] = candidate
                        break
                break

        for i, line in enumerate(lines):
            if re.search(r'Employee.*name.*address', line, re.IGNORECASE):
                for j in range(i + 1, min(i + 4, len(lines))):
                    candidate = lines[j].strip()
                    if candidate and re.match(r'^[A-Z][A-Z\s]+$', candidate) and len(candidate.split()) >= 2:
                        data['employee_name'] = candidate
                        break
                break

        if not data.get('wages_tips_compensation'):
            return None

        return data

    def _extract_dollar_amount(self, text: str) -> Optional[str]:
        import re
        match = re.search(r'[\d,]+\.\d{2}', text)
        if match:
            return match.group().replace(',', '')
        return None

    def _call_1099_endpoint(self, pdf_b64: str, form_type: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.post(
                f"{self.flyfield_url}/extract/1099_{form_type}",
                json={'pdf': pdf_b64},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def extract_1099_int_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        with open(file_path, 'rb') as f:
            pdf_b64 = base64.b64encode(f.read()).decode()

        result = self._call_1099_endpoint(pdf_b64, 'int')
        if not result or not result.get('success'):
            return None

        data = result.get('data', {})
        if not data:
            return None

        normalized = {
            'payer_name': data.get('payer_name'),
            'payer_ein': data.get('payer_ein'),
            'recipient_name': data.get('recipient_name'),
            'recipient_ssn': data.get('recipient_ssn'),
            'account_number': data.get('account_number'),
            'interest_income': data.get('box_1_interest_income'),
            'tax_exempt_interest': data.get('box_8_tax_exempt_interest'),
            'federal_tax_withheld': data.get('box_4_federal_withholding'),
            'foreign_tax_paid': data.get('box_6_foreign_tax_paid'),
        }
        return normalized if any(v is not None for v in normalized.values()) else None

    def extract_1099_div_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        with open(file_path, 'rb') as f:
            pdf_b64 = base64.b64encode(f.read()).decode()

        result = self._call_1099_endpoint(pdf_b64, 'div')
        if not result or not result.get('success'):
            return None

        data = result.get('data', {})
        if not data:
            return None

        normalized = {
            'payer_name': data.get('payer_name'),
            'payer_ein': data.get('payer_ein'),
            'recipient_name': data.get('recipient_name'),
            'recipient_ssn': data.get('recipient_ssn'),
            'account_number': data.get('account_number'),
            'total_ordinary_dividends': data.get('box_1a_total_ordinary_dividends'),
            'qualified_dividends': data.get('box_1b_qualified_dividends'),
            'section_199a_dividends': data.get('box_5_section_199a'),
            'federal_tax_withheld': data.get('box_4_federal_withholding'),
            'foreign_tax_paid': data.get('box_7_foreign_tax_paid'),
            'exempt_interest_dividends': data.get('box_12_exempt_interest_dividends'),
        }
        return normalized if any(v is not None for v in normalized.values()) else None


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        extractor = FlyfieldExtractor()
        result = extractor.extract_w2_from_file(sys.argv[1])
        print(result)
