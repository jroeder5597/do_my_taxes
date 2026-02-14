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
from .prompts import PromptTemplates

logger = get_logger(__name__)

# Try to import ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama package not installed. LLM extraction will not be available.")


class LLMExtractor:
    """
    Extract structured tax data from OCR text using LLM.
    """
    
    def __init__(
        self,
        model: str = "gpt-oss:20b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
    ):
        """
        Initialize the LLM extractor.
        
        Args:
            model: Ollama model name
            base_url: Ollama API base URL
            temperature: Temperature for generation
        """
        if not OLLAMA_AVAILABLE:
            raise RuntimeError(
                "ollama package is not installed. Install with: pip install ollama"
            )
        
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        
        # Configure ollama client
        self.client = ollama.Client(host=base_url)
        
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
                    "temperature": self.temperature,
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
            # Parse box 12 codes
            box_12_codes = []
            for item in data.get("box_12_codes", []):
                if item.get("code") and item.get("amount") is not None:
                    box_12_codes.append(Box12Code(
                        code=item["code"],
                        amount=Decimal(str(item["amount"])),
                    ))
            
            # Parse box 14 items
            box_14_other = []
            for item in data.get("box_14_other", []):
                if item.get("description"):
                    box_14_other.append(Box14Item(
                        description=item["description"],
                        amount=Decimal(str(item["amount"])) if item.get("amount") is not None else None,
                    ))
            
            return W2Data(
                document_id=document_id,
                employer_ein=data.get("employer_ein"),
                employer_name=data.get("employer_name", ""),
                employer_address=data.get("employer_address"),
                employer_city=data.get("employer_city"),
                employer_state=data.get("employer_state"),
                employer_zip=data.get("employer_zip"),
                employee_name=data.get("employee_name", ""),
                employee_ssn=data.get("employee_ssn"),
                employee_address=data.get("employee_address"),
                employee_city=data.get("employee_city"),
                employee_state=data.get("employee_state"),
                employee_zip=data.get("employee_zip"),
                control_number=data.get("control_number"),
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
            # Parse state info
            state_info = []
            for item in data.get("state_info", []):
                if item.get("state"):
                    state_info.append(StateInfo(
                        state=item["state"],
                        state_id=item.get("state_id"),
                        state_tax_withheld=Decimal(str(item["state_tax_withheld"])) if item.get("state_tax_withheld") is not None else None,
                    ))
            
            return Form1099INT(
                document_id=document_id,
                payer_name=data.get("payer_name", ""),
                payer_address=data.get("payer_address"),
                payer_tin=data.get("payer_tin"),
                recipient_name=data.get("recipient_name", ""),
                recipient_tin=data.get("recipient_tin"),
                recipient_address=data.get("recipient_address"),
                interest_income=Decimal(str(data.get("interest_income", 0))),
                early_withdrawal_penalty=Decimal(str(data["early_withdrawal_penalty"])) if data.get("early_withdrawal_penalty") is not None else None,
                interest_on_us_savings_bonds=Decimal(str(data["interest_on_us_savings_bonds"])) if data.get("interest_on_us_savings_bonds") is not None else None,
                federal_income_tax_withheld=Decimal(str(data["federal_income_tax_withheld"])) if data.get("federal_income_tax_withheld") is not None else None,
                investment_expenses=Decimal(str(data["investment_expenses"])) if data.get("investment_expenses") is not None else None,
                foreign_tax_paid=Decimal(str(data["foreign_tax_paid"])) if data.get("foreign_tax_paid") is not None else None,
                foreign_country=data.get("foreign_country"),
                tax_exempt_interest=Decimal(str(data["tax_exempt_interest"])) if data.get("tax_exempt_interest") is not None else None,
                specified_private_activity_bond_interest=Decimal(str(data["specified_private_activity_bond_interest"])) if data.get("specified_private_activity_bond_interest") is not None else None,
                market_discount=Decimal(str(data["market_discount"])) if data.get("market_discount") is not None else None,
                bond_premium=Decimal(str(data["bond_premium"])) if data.get("bond_premium") is not None else None,
                bond_premium_treasury_obligations=Decimal(str(data["bond_premium_treasury_obligations"])) if data.get("bond_premium_treasury_obligations") is not None else None,
                bond_premium_tax_exempt_bond=Decimal(str(data["bond_premium_tax_exempt_bond"])) if data.get("bond_premium_tax_exempt_bond") is not None else None,
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
            # Parse state info
            state_info = []
            for item in data.get("state_info", []):
                if item.get("state"):
                    state_info.append(StateInfo(
                        state=item["state"],
                        state_id=item.get("state_id"),
                        state_tax_withheld=Decimal(str(item["state_tax_withheld"])) if item.get("state_tax_withheld") is not None else None,
                    ))
            
            return Form1099DIV(
                document_id=document_id,
                payer_name=data.get("payer_name", ""),
                payer_address=data.get("payer_address"),
                payer_tin=data.get("payer_tin"),
                recipient_name=data.get("recipient_name", ""),
                recipient_tin=data.get("recipient_tin"),
                recipient_address=data.get("recipient_address"),
                total_ordinary_dividends=Decimal(str(data.get("total_ordinary_dividends", 0))),
                qualified_dividends=Decimal(str(data["qualified_dividends"])) if data.get("qualified_dividends") is not None else None,
                total_capital_gain=Decimal(str(data["total_capital_gain"])) if data.get("total_capital_gain") is not None else None,
                unrecaptured_section_1250_gain=Decimal(str(data["unrecaptured_section_1250_gain"])) if data.get("unrecaptured_section_1250_gain") is not None else None,
                section_1202_gain=Decimal(str(data["section_1202_gain"])) if data.get("section_1202_gain") is not None else None,
                collectibles_gain=Decimal(str(data["collectibles_gain"])) if data.get("collectibles_gain") is not None else None,
                section_897_ordinary_dividends=Decimal(str(data["section_897_ordinary_dividends"])) if data.get("section_897_ordinary_dividends") is not None else None,
                section_897_capital_gain=Decimal(str(data["section_897_capital_gain"])) if data.get("section_897_capital_gain") is not None else None,
                nondividend_distributions=Decimal(str(data["nondividend_distributions"])) if data.get("nondividend_distributions") is not None else None,
                federal_income_tax_withheld=Decimal(str(data["federal_income_tax_withheld"])) if data.get("federal_income_tax_withheld") is not None else None,
                section_199a_dividends=Decimal(str(data["section_199a_dividends"])) if data.get("section_199a_dividends") is not None else None,
                investment_expenses=Decimal(str(data["investment_expenses"])) if data.get("investment_expenses") is not None else None,
                foreign_tax_paid=Decimal(str(data["foreign_tax_paid"])) if data.get("foreign_tax_paid") is not None else None,
                foreign_country=data.get("foreign_country"),
                cash_liquidation=Decimal(str(data["cash_liquidation"])) if data.get("cash_liquidation") is not None else None,
                noncash_liquidation=Decimal(str(data["noncash_liquidation"])) if data.get("noncash_liquidation") is not None else None,
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