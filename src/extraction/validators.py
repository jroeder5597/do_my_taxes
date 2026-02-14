"""
Data validation module for extracted tax data.
"""

from decimal import Decimal
from typing import Any, Optional

from src.storage.models import (
    DocumentType,
    Form1099DIV,
    Form1099INT,
    W2Data,
)
from src.utils import get_logger

logger = get_logger(__name__)


class DataValidator:
    """
    Validate extracted tax data for completeness and accuracy.
    """
    
    # Required fields for each document type
    REQUIRED_FIELDS = {
        DocumentType.W2: [
            "employer_name",
            "employee_name",
            "wages_tips_compensation",
            "federal_income_tax_withheld",
            "social_security_wages",
            "social_security_tax_withheld",
            "medicare_wages",
            "medicare_tax_withheld",
        ],
        DocumentType.FORM_1099_INT: [
            "payer_name",
            "interest_income",
        ],
        DocumentType.FORM_1099_DIV: [
            "payer_name",
            "total_ordinary_dividends",
        ],
    }
    
    # Tax year limits for validation
    SS_WAGE_LIMIT_2024 = Decimal("168600")  # Social Security wage base for 2024
    SS_TAX_RATE = Decimal("0.062")  # 6.2%
    MEDICARE_TAX_RATE = Decimal("0.0145")  # 1.45%
    
    def __init__(self, tax_year: int = 2024):
        """
        Initialize the validator.
        
        Args:
            tax_year: Tax year for validation rules
        """
        self.tax_year = tax_year
    
    def validate_w2(self, data: W2Data) -> tuple[bool, list[str]]:
        """
        Validate W-2 form data.
        
        Args:
            data: W2Data object to validate
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        warnings = []
        
        # Check required fields
        if not data.employer_name:
            errors.append("Missing employer name")
        
        if not data.employee_name:
            errors.append("Missing employee name")
        
        if data.wages_tips_compensation is None:
            errors.append("Missing wages/tips/compensation (Box 1)")
        elif data.wages_tips_compensation < 0:
            errors.append("Wages cannot be negative")
        
        # Validate Social Security tax calculation
        if data.social_security_wages and data.social_security_tax_withheld:
            expected_ss_tax = min(
                data.social_security_wages * self.SS_TAX_RATE,
                self.SS_WAGE_LIMIT_2024 * self.SS_TAX_RATE
            )
            actual_ss_tax = data.social_security_tax_withheld
            
            # Allow small rounding differences
            if abs(expected_ss_tax - actual_ss_tax) > Decimal("1.00"):
                warnings.append(
                    f"Social Security tax ({actual_ss_tax}) doesn't match expected "
                    f"({expected_ss_tax:.2f}) based on SS wages ({data.social_security_wages})"
                )
        
        # Validate Medicare tax calculation
        if data.medicare_wages and data.medicare_tax_withheld:
            expected_medicare_tax = data.medicare_wages * self.MEDICARE_TAX_RATE
            actual_medicare_tax = data.medicare_tax_withheld
            
            # Allow small rounding differences
            if abs(expected_medicare_tax - actual_medicare_tax) > Decimal("1.00"):
                warnings.append(
                    f"Medicare tax ({actual_medicare_tax}) doesn't match expected "
                    f"({expected_medicare_tax:.2f}) based on Medicare wages ({data.medicare_wages})"
                )
        
        # Validate SSN format
        if data.employee_ssn:
            import re
            if not re.match(r"^\d{3}-\d{2}-\d{4}$", data.employee_ssn):
                warnings.append(f"SSN format may be incorrect: {data.employee_ssn[:3]}-XX-XXXX")
        
        # Validate EIN format
        if data.employer_ein:
            import re
            if not re.match(r"^\d{2}-\d{7}$", data.employer_ein):
                warnings.append(f"EIN format may be incorrect: {data.employer_ein}")
        
        # Log warnings
        for warning in warnings:
            logger.warning(f"W-2 validation warning: {warning}")
        
        # Log errors
        for error in errors:
            logger.error(f"W-2 validation error: {error}")
        
        return len(errors) == 0, errors + [f"WARNING: {w}" for w in warnings]
    
    def validate_1099_int(self, data: Form1099INT) -> tuple[bool, list[str]]:
        """
        Validate 1099-INT form data.
        
        Args:
            data: Form1099INT object to validate
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        warnings = []
        
        # Check required fields
        if not data.payer_name:
            errors.append("Missing payer name")
        
        if data.interest_income is None:
            errors.append("Missing interest income (Box 1)")
        elif data.interest_income < 0:
            errors.append("Interest income cannot be negative")
        
        # Validate that interest income is reasonable
        if data.interest_income and data.interest_income > Decimal("1000000"):
            warnings.append(f"Interest income is unusually high: ${data.interest_income:,.2f}")
        
        # Check for tax-exempt interest
        if data.tax_exempt_interest and data.tax_exempt_interest > 0:
            warnings.append(
                "Tax-exempt interest detected. This may need to be reported on Form 1040, "
                "Schedule 2 even though it's not taxable."
            )
        
        # Log warnings
        for warning in warnings:
            logger.warning(f"1099-INT validation warning: {warning}")
        
        # Log errors
        for error in errors:
            logger.error(f"1099-INT validation error: {error}")
        
        return len(errors) == 0, errors + [f"WARNING: {w}" for w in warnings]
    
    def validate_1099_div(self, data: Form1099DIV) -> tuple[bool, list[str]]:
        """
        Validate 1099-DIV form data.
        
        Args:
            data: Form1099DIV object to validate
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        warnings = []
        
        # Check required fields
        if not data.payer_name:
            errors.append("Missing payer name")
        
        if data.total_ordinary_dividends is None:
            errors.append("Missing total ordinary dividends (Box 1a)")
        elif data.total_ordinary_dividends < 0:
            errors.append("Dividends cannot be negative")
        
        # Validate qualified dividends <= total dividends
        if data.qualified_dividends and data.total_ordinary_dividends:
            if data.qualified_dividends > data.total_ordinary_dividends:
                errors.append(
                    f"Qualified dividends ({data.qualified_dividends}) cannot exceed "
                    f"total ordinary dividends ({data.total_ordinary_dividends})"
                )
        
        # Validate capital gain <= total dividends (typically)
        if data.total_capital_gain and data.total_ordinary_dividends:
            if data.total_capital_gain > data.total_ordinary_dividends:
                warnings.append(
                    f"Capital gain distributions ({data.total_capital_gain}) exceed "
                    f"total ordinary dividends ({data.total_ordinary_dividends})"
                )
        
        # Check for foreign tax paid
        if data.foreign_tax_paid and data.foreign_tax_paid > 0:
            warnings.append(
                "Foreign tax paid detected. You may be eligible for foreign tax credit "
                "(Form 1116)."
            )
        
        # Log warnings
        for warning in warnings:
            logger.warning(f"1099-DIV validation warning: {warning}")
        
        # Log errors
        for error in errors:
            logger.error(f"1099-DIV validation error: {error}")
        
        return len(errors) == 0, errors + [f"WARNING: {w}" for w in warnings]
    
    def validate(
        self,
        data: W2Data | Form1099INT | Form1099DIV,
        document_type: DocumentType,
    ) -> tuple[bool, list[str]]:
        """
        Validate extracted data based on document type.
        
        Args:
            data: Extracted data object
            document_type: Type of tax document
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        validators = {
            DocumentType.W2: self.validate_w2,
            DocumentType.FORM_1099_INT: self.validate_1099_int,
            DocumentType.FORM_1099_DIV: self.validate_1099_div,
        }
        
        validator = validators.get(document_type)
        
        if validator is None:
            logger.warning(f"No validator for document type: {document_type}")
            return True, []
        
        return validator(data)
    
    def check_missing_fields(
        self,
        data: dict[str, Any],
        document_type: DocumentType,
    ) -> list[str]:
        """
        Check for missing required fields in extracted data.
        
        Args:
            data: Extracted data dictionary
            document_type: Type of tax document
        
        Returns:
            List of missing field names
        """
        required = self.REQUIRED_FIELDS.get(document_type, [])
        missing = []
        
        for field in required:
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        
        return missing
    
    def suggest_corrections(
        self,
        data: dict[str, Any],
        document_type: DocumentType,
    ) -> list[str]:
        """
        Suggest corrections for common extraction errors.
        
        Args:
            data: Extracted data dictionary
            document_type: Type of tax document
        
        Returns:
            List of correction suggestions
        """
        suggestions = []
        
        # Check for common OCR errors
        for key, value in data.items():
            if value is None:
                continue
            
            if isinstance(value, str):
                # Check for common OCR misreads
                if "O" in value and any(c.isdigit() for c in value):
                    suggestions.append(
                        f"Field '{key}' may have OCR errors (O vs 0): {value}"
                    )
                
                if "l" in value and any(c.isdigit() for c in value):
                    suggestions.append(
                        f"Field '{key}' may have OCR errors (l vs 1): {value}"
                    )
            
            # Check for negative values where not expected
            if isinstance(value, (int, float, Decimal)):
                if value < 0 and key not in ["early_withdrawal_penalty"]:
                    suggestions.append(
                        f"Field '{key}' has negative value: {value}"
                    )
        
        return suggestions