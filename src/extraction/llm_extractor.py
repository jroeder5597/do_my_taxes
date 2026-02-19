"""
LLM-based data extraction module.
Uses Ollama to extract structured data from tax documents.
"""

import json
from decimal import Decimal
from typing import Any, Optional

from src.storage.models import (
    DocumentType,
    Form1099DIV,
    Form1099INT,
    W2Data,
    Box12Code,
    Box14Item,
    StateInfo,
)
from src.utils import get_logger
from src.utils.config import get_settings
from .prompts import PromptTemplates

logger = get_logger(__name__)

# Try to import ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama package not installed. LLM extraction will not be available.")


def round_decimal(val):
    """Round a value to 2 decimal places for currency."""
    if val is None:
        return None
    return Decimal(str(val)).quantize(Decimal('0.01'))


class LLMExtractor:
    """
    Extract structured tax data from OCR text using LLM.
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        """
        Initialize the LLM extractor.
        
        Args:
            model: Ollama model name (defaults to config value)
            base_url: Ollama API base URL (defaults to config value)
            temperature: Temperature for generation (defaults to config value)
        """
        if not OLLAMA_AVAILABLE:
            raise RuntimeError(
                "ollama package is not installed. Install with: pip install ollama"
            )
        
        # Get settings from config
        settings = get_settings()
        
        self.model = model or settings.llm.ollama.model
        self.base_url = base_url or settings.llm.ollama.base_url
        self.temperature = temperature if temperature is not None else settings.llm.ollama.extraction_options.temperature
        
        # Configure ollama client
        self.client = ollama.Client(host=self.base_url)
        
        # Verify model is available
        self._verify_model()
    
    def _verify_model(self) -> None:
        """Verify that the model is available in Ollama."""
        try:
            models = self.client.list()
            model_names = [m.get("model", "") for m in models.get("models", [])]
            
            # Check if model exists (with or without tag)
            model_base = self.model.split(":")[0]
            model_available = any(
                m == self.model or m.startswith(f"{model_base}:") or m == model_base
                for m in model_names
            )
            
            if not model_available:
                logger.warning(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Available models: {model_names}. "
                    f"You may need to pull the model: ollama pull {self.model}"
                )
        except Exception as e:
            logger.warning(f"Could not verify model availability: {e}")
    
    def _preprocess_ocr_text(self, text: str) -> str:
        """
        Preprocess OCR text to improve extraction accuracy.
        Focus on extracting only relevant box values.
        
        Args:
            text: Raw OCR text
        
        Returns:
            Preprocessed text
        """
        import re
        
        # Split into lines
        lines = text.split('\n')
        
        # Extract relevant lines based on multiple criteria
        relevant_lines = []
        for line in lines:
            # Keep lines with dollar amounts (numbers with decimals)
            has_dollar = re.search(r'\d+\.\d{2}', line)
            
            # Keep lines with box indicators
            has_box = re.search(r'[0-9]\s+[A-Za-z]|Box\s*[0-9]', line, re.IGNORECASE)
            
            # Keep lines with ALL CAPS company/employee names (2+ consecutive caps)
            has_caps = re.search(r'[A-Z]{3,}', line)
            
            # Keep lines with common W-2 keywords
            has_keyword = re.search(r'wages|tax|compensation|withheld|employer|employee|state|federal|social|medicare', line, re.IGNORECASE)
            
            # Include line if it matches any criteria
            if has_dollar or has_box or (has_caps and has_keyword) or (has_caps and len(line.strip()) < 50):
                relevant_lines.append(line)
        
        # If we found relevant lines, use those
        if relevant_lines:
            result = '\n'.join(relevant_lines)
            
            # Add extra context: extract key values from original text
            # Find employer name
            employer_match = re.search(r"(?:Employer['\u2019]?s?[-\s]?(?:name|company)|c\s+Employer)[^\n]*([A-Z][A-Z\s]+?)(?:\n|P|O|B)", text, re.IGNORECASE)
            
            # Add some key context at the top
            header = "W-2 DOCUMENT:\n"
            if employer_match:
                header += f"Employer: {employer_match.group(1).strip()}\n"
            
            return header + result
        
        # Fallback: just clean up the text
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    def extract(
        self,
        ocr_text: str,
        document_type: DocumentType,
    ) -> dict[str, Any]:
        """
        Extract structured data from OCR text.
        
        Args:
            ocr_text: OCR text from the document
            document_type: Type of tax document
        
        Returns:
            Extracted data as dictionary
        """
        logger.info(f"Extracting data from {document_type.value} document")
        
        # Preprocess OCR text to improve extraction
        ocr_text = self._preprocess_ocr_text(ocr_text)
        
        # Get the appropriate prompt
        prompt = PromptTemplates.get_extraction_prompt(document_type, ocr_text)
        
        try:
            # Call Ollama API
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": PromptTemplates.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={
                    "temperature": 0,  # Force deterministic output
                },
                format="json",  # Request JSON output
            )
            
            # Extract content from response
            content = response.get("message", {}).get("content", "{}")
            
            # Parse JSON response
            data = json.loads(content)
            
            logger.info(f"Successfully extracted {len(data)} fields")
            return data
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            raise
    
    def extract_w2(self, ocr_text: str, document_id: int) -> Optional[W2Data]:
        """
        Extract W-2 form data.
        
        Args:
            ocr_text: OCR text from the W-2 form
            document_id: Document ID for reference
        
        Returns:
            W2Data object or None if extraction failed
        """
        data = self.extract(ocr_text, DocumentType.W2)
        
        if not data:
            return None
        
        try:
            # Parse box 12 codes (handle case where LLM returns string instead of list)
            box_12_codes = []
            box_12_data = data.get("box_12_codes", [])
            if isinstance(box_12_data, list):
                for item in box_12_data:
                    if isinstance(item, dict) and item.get("code"):
                        code = item.get("code", "")
                        amount = item.get("amount")
                        if code and amount is not None:
                            # Truncate code to max 2 characters (W-2 Box 12 codes are 1-2 letters)
                            code = str(code)[:2].upper()
                            box_12_codes.append(Box12Code(
                                code=code,
                                amount=Decimal(str(amount)),
                            ))
            elif isinstance(box_12_data, dict):
                # Handle case where it's a single dict instead of list
                if box_12_data.get("code"):
                    code = str(box_12_data.get("code", ""))[:2].upper()
                    amount = box_12_data.get("amount")
                    if amount is not None:
                        box_12_codes.append(Box12Code(
                            code=code,
                            amount=Decimal(str(amount)),
                        ))
            
            # Parse box 14 items (handle case where LLM returns string instead of list)
            box_14_other = []
            box_14_data = data.get("box_14_other", [])
            if isinstance(box_14_data, list):
                for item in box_14_data:
                    if isinstance(item, dict) and item.get("description"):
                        box_14_other.append(Box14Item(
                            description=item["description"],
                            amount=Decimal(str(item["amount"])) if item.get("amount") is not None else None,
                        ))
            elif isinstance(box_14_data, dict):
                # Handle case where it's a single dict instead of list
                if box_14_data.get("description"):
                    box_14_other.append(Box14Item(
                        description=box_14_data["description"],
                        amount=Decimal(str(box_14_data.get("amount"))) if box_14_data.get("amount") is not None else None,
                    ))
            
            # Format EIN (XX-XXXXXXX) - must be exactly 9 digits
            ein = data.get("employer_ein")
            if ein:
                ein_digits = "".join(c for c in str(ein) if c.isdigit())
                if len(ein_digits) == 9:
                    ein = f"{ein_digits[:2]}-{ein_digits[2:]}"
                else:
                    logger.warning(f"Invalid EIN format: {ein}, expected 9 digits, got {len(ein_digits)}")
                    ein = None
            
            # Format SSN (XXX-XX-XXXX) - must be exactly 9 digits
            ssn = data.get("employee_ssn")
            if ssn:
                ssn_digits = "".join(c for c in str(ssn) if c.isdigit())
                if len(ssn_digits) == 9:
                    ssn = f"{ssn_digits[:3]}-{ssn_digits[3:5]}-{ssn_digits[5:]}"
                else:
                    logger.warning(f"Invalid SSN format: {ssn}, expected 9 digits, got {len(ssn_digits)}")
                    ssn = None
            
            # Format control number as string
            control_number = data.get("control_number")
            if control_number is not None:
                control_number = str(control_number)
            
            return W2Data(
                document_id=document_id,
                employer_ein=ein,
                employer_name=data.get("employer_name") or "",
                employer_address=data.get("employer_address"),
                employer_city=data.get("employer_city"),
                employer_state=data.get("employer_state"),
                employer_zip=data.get("employer_zip"),
                employee_name=data.get("employee_name") or "",
                employee_ssn=ssn,
                employee_address=data.get("employee_address"),
                employee_city=data.get("employee_city"),
                employee_state=data.get("employee_state"),
                employee_zip=data.get("employee_zip"),
                control_number=control_number,
                wages_tips_compensation=Decimal(str(data.get("wages_tips_compensation", 0))),
                federal_income_tax_withheld=Decimal(str(data.get("federal_income_tax_withheld", 0))),
                social_security_wages=Decimal(str(data.get("social_security_wages", 0))),
                social_security_tax_withheld=Decimal(str(data.get("social_security_tax_withheld", 0))),
                medicare_wages=Decimal(str(data.get("medicare_wages", 0))),
                medicare_tax_withheld=Decimal(str(data.get("medicare_tax_withheld", 0))),
                social_security_tips=Decimal(str(data["social_security_tips"])) if data.get("social_security_tips") is not None else None,
                allocated_tips=Decimal(str(data["allocated_tips"])) if data.get("allocated_tips") is not None else None,
                dependent_care_benefits=Decimal(str(data["dependent_care_benefits"])) if data.get("dependent_care_benefits") is not None else None,
                nonqualified_plans=Decimal(str(data["nonqualified_plans"])) if data.get("nonqualified_plans") is not None else None,
                box_12_codes=box_12_codes,
                statutory_employee=bool(data.get("statutory_employee", False)),
                retirement_plan=bool(data.get("retirement_plan", False)),
                third_party_sick_pay=bool(data.get("third_party_sick_pay", False)),
                box_14_other=box_14_other,
                state_employer_state_id=data.get("state_employer_state_id"),
                state_wages_tips=Decimal(str(data["state_wages_tips"])) if data.get("state_wages_tips") is not None else None,
                state_income_tax=Decimal(str(data["state_income_tax"])) if data.get("state_income_tax") is not None else None,
                local_wages_tips=Decimal(str(data["local_wages_tips"])) if data.get("local_wages_tips") is not None else None,
                local_income_tax=Decimal(str(data["local_income_tax"])) if data.get("local_income_tax") is not None else None,
                locality_name=data.get("locality_name"),
                raw_data=data,
            )
        
        except Exception as e:
            logger.error(f"Failed to create W2Data object: {e}")
            return None
    
    def extract_1099_int(self, ocr_text: str, document_id: int) -> Optional[Form1099INT]:
        """
        Extract 1099-INT form data.
        
        Args:
            ocr_text: OCR text from the 1099-INT form
            document_id: Document ID for reference
        
        Returns:
            Form1099INT object or None if extraction failed
        """
        data = self.extract(ocr_text, DocumentType.FORM_1099_INT)
        
        if not data:
            return None
        
        try:
            # Parse state info (handle case where LLM returns string/dict instead of list)
            state_info = []
            state_data = data.get("state_info", [])
            if isinstance(state_data, list):
                for item in state_data:
                    if isinstance(item, dict) and item.get("state"):
                        state_info.append(StateInfo(
                            state=item["state"],
                            state_id=item.get("state_id"),
                            state_tax_withheld=round_decimal(item.get("state_tax_withheld")),
                        ))
            elif isinstance(state_data, dict) and state_data.get("state"):
                state_info.append(StateInfo(
                    state=state_data["state"],
                    state_id=state_data.get("state_id"),
                    state_tax_withheld=round_decimal(state_data.get("state_tax_withheld")),
                ))
            
            return Form1099INT(
                document_id=document_id,
                payer_name=data.get("payer_name") or "",
                payer_address=data.get("payer_address"),
                payer_tin=data.get("payer_tin"),
                recipient_name=data.get("recipient_name") or "",
                recipient_tin=data.get("recipient_tin"),
                recipient_address=data.get("recipient_address"),
                interest_income=round_decimal(data.get("interest_income", 0)),
                early_withdrawal_penalty=round_decimal(data.get("early_withdrawal_penalty")),
                interest_on_us_savings_bonds=round_decimal(data.get("interest_on_us_savings_bonds")),
                federal_income_tax_withheld=round_decimal(data.get("federal_income_tax_withheld")),
                investment_expenses=round_decimal(data.get("investment_expenses")),
                foreign_tax_paid=round_decimal(data.get("foreign_tax_paid")),
                foreign_country=data.get("foreign_country"),
                tax_exempt_interest=round_decimal(data.get("tax_exempt_interest")),
                specified_private_activity_bond_interest=round_decimal(data.get("specified_private_activity_bond_interest")),
                market_discount=round_decimal(data.get("market_discount")),
                bond_premium=round_decimal(data.get("bond_premium")),
                bond_premium_treasury_obligations=round_decimal(data.get("bond_premium_treasury_obligations")),
                bond_premium_tax_exempt_bond=round_decimal(data.get("bond_premium_tax_exempt_bond")),
                tax_exempt_cusip_number=data.get("tax_exempt_cusip_number"),
                state_info=state_info,
                raw_data=data,
            )
        
        except Exception as e:
            logger.error(f"Failed to create Form1099INT object: {e}")
            return None
    
    def extract_1099_div(self, ocr_text: str, document_id: int) -> Optional[Form1099DIV]:
        """
        Extract 1099-DIV form data.
        
        Args:
            ocr_text: OCR text from the 1099-DIV form
            document_id: Document ID for reference
        
        Returns:
            Form1099DIV object or None if extraction failed
        """
        data = self.extract(ocr_text, DocumentType.FORM_1099_DIV)
        
        if not data:
            return None
        
        try:
            # Helper to round decimal to 2 places
            def round_decimal(val):
                if val is None:
                    return None
                return Decimal(str(val)).quantize(Decimal('0.01'))
            
            # Parse state info (handle case where LLM returns string/dict instead of list)
            state_info = []
            state_data = data.get("state_info", [])
            if isinstance(state_data, list):
                for item in state_data:
                    if isinstance(item, dict) and item.get("state"):
                        state_info.append(StateInfo(
                            state=item["state"],
                            state_id=item.get("state_id"),
                            state_tax_withheld=round_decimal(item.get("state_tax_withheld")),
                        ))
            elif isinstance(state_data, dict) and state_data.get("state"):
                state_info.append(StateInfo(
                    state=state_data["state"],
                    state_id=state_data.get("state_id"),
                    state_tax_withheld=round_decimal(state_data.get("state_tax_withheld")),
                ))
            
            return Form1099DIV(
                document_id=document_id,
                payer_name=data.get("payer_name") or "",
                payer_address=data.get("payer_address"),
                payer_tin=data.get("payer_tin"),
                recipient_name=data.get("recipient_name") or "",
                recipient_tin=data.get("recipient_tin"),
                recipient_address=data.get("recipient_address"),
                total_ordinary_dividends=round_decimal(data.get("total_ordinary_dividends")) or Decimal('0.00'),
                qualified_dividends=round_decimal(data.get("qualified_dividends")),
                total_capital_gain=round_decimal(data.get("total_capital_gain")),
                unrecaptured_section_1250_gain=round_decimal(data.get("unrecaptured_section_1250_gain")),
                section_1202_gain=round_decimal(data.get("section_1202_gain")),
                collectibles_gain=round_decimal(data.get("collectibles_gain")),
                section_897_ordinary_dividends=round_decimal(data.get("section_897_ordinary_dividends")),
                section_897_capital_gain=round_decimal(data.get("section_897_capital_gain")),
                nondividend_distributions=round_decimal(data.get("nondividend_distributions")),
                federal_income_tax_withheld=round_decimal(data.get("federal_income_tax_withheld")),
                section_199a_dividends=round_decimal(data.get("section_199a_dividends")),
                investment_expenses=round_decimal(data.get("investment_expenses")),
                foreign_tax_paid=round_decimal(data.get("foreign_tax_paid")),
                foreign_country=data.get("foreign_country"),
                cash_liquidation=round_decimal(data.get("cash_liquidation")),
                noncash_liquidation=round_decimal(data.get("noncash_liquidation")),
                fatca_filing=bool(data.get("fatca_filing", False)),
                state_info=state_info,
                raw_data=data,
            )
        
        except Exception as e:
            logger.error(f"Failed to create Form1099DIV object: {e}")
            return None
    
    def chat(self, messages: list[dict], temperature: Optional[float] = None) -> str:
        """
        Send a chat message to the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            temperature: Optional temperature override
        
        Returns:
            LLM response text
        """
        try:
            response = self.client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": temperature or self.temperature,
                },
            )
            
            return response.get("message", {}).get("content", "")
        
        except Exception as e:
            logger.error(f"Chat request failed: {e}")
            raise
    
    def check_connection(self) -> bool:
        """
        Check if Ollama is running and accessible.
        
        Returns:
            True if connection is successful
        """
        try:
            self.client.list()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False