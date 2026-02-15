"""
Data models for tax document storage.
Uses Pydantic for validation and serialization.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class DocumentType(str, Enum):
    """Supported tax document types."""
    
    W2 = "W2"
    FORM_1099_INT = "1099_INT"
    FORM_1099_DIV = "1099_DIV"
    FORM_1099_B = "1099_B"
    FORM_1099_NEC = "1099_NEC"
    FORM_1099_G = "1099_G"
    FORM_1099_R = "1099_R"
    FORM_1098 = "1098"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ProcessingStatus(str, Enum):
    """Document processing status."""
    
    PENDING = "pending"
    PROCESSING = "processing"
    OCR_COMPLETE = "ocr_complete"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    ERROR = "error"


class TaxYear(BaseModel):
    """Tax year record."""
    
    id: Optional[int] = None
    year: int = Field(..., ge=2020, le=2030)
    filing_status: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True


class Document(BaseModel):
    """Document record."""
    
    id: Optional[int] = None
    tax_year_id: int
    document_type: DocumentType
    file_name: str
    file_path: str
    file_hash: str
    ocr_text: Optional[str] = None
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True


class Box12Code(BaseModel):
    """W-2 Box 12 code and amount."""
    
    code: str = Field(..., min_length=1, max_length=2)
    amount: Decimal = Field(..., decimal_places=2)
    
    class Config:
        json_encoders = {Decimal: str}


class Box14Item(BaseModel):
    """W-2 Box 14 item."""
    
    description: str
    amount: Optional[Decimal] = Field(None, decimal_places=2)
    
    class Config:
        json_encoders = {Decimal: str}


class W2Data(BaseModel):
    """W-2 form extracted data."""
    
    id: Optional[int] = None
    document_id: int
    
    # Employer Information
    employer_ein: Optional[str] = Field(None, pattern=r"^\d{2}-\d{7}$")
    employer_name: str
    employer_address: Optional[str] = None
    employer_city: Optional[str] = None
    employer_state: Optional[str] = None
    employer_zip: Optional[str] = None
    
    # Employee Information
    employee_name: str
    employee_ssn: Optional[str] = Field(None, pattern=r"^\d{3}-\d{2}-\d{4}$")
    employee_address: Optional[str] = None
    employee_city: Optional[str] = None
    employee_state: Optional[str] = None
    employee_zip: Optional[str] = None
    
    # Control Number
    control_number: Optional[str] = None
    
    # Income and Tax Data
    wages_tips_compensation: Decimal = Field(..., decimal_places=2)
    federal_income_tax_withheld: Decimal = Field(..., decimal_places=2)
    social_security_wages: Decimal = Field(..., decimal_places=2)
    social_security_tax_withheld: Decimal = Field(..., decimal_places=2)
    medicare_wages: Decimal = Field(..., decimal_places=2)
    medicare_tax_withheld: Decimal = Field(..., decimal_places=2)
    social_security_tips: Optional[Decimal] = Field(None, decimal_places=2)
    allocated_tips: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Additional Boxes
    dependent_care_benefits: Optional[Decimal] = Field(None, decimal_places=2)
    nonqualified_plans: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Box 12 - Codes and Amounts
    box_12_codes: list[Box12Code] = Field(default_factory=list)
    
    # Box 13 - Checkboxes
    statutory_employee: bool = False
    retirement_plan: bool = False
    third_party_sick_pay: bool = False
    
    # Box 14 - Other
    box_14_other: list[Box14Item] = Field(default_factory=list)
    
    # State/Local Information
    state_employer_state_id: Optional[str] = None
    state_wages_tips: Optional[Decimal] = Field(None, decimal_places=2)
    state_income_tax: Optional[Decimal] = Field(None, decimal_places=2)
    local_wages_tips: Optional[Decimal] = Field(None, decimal_places=2)
    local_income_tax: Optional[Decimal] = Field(None, decimal_places=2)
    locality_name: Optional[str] = None
    
    # Raw extracted data (JSON)
    raw_data: Optional[dict[str, Any]] = None
    
    class Config:
        from_attributes = True
        json_encoders = {Decimal: str}
    
    @field_validator("employer_ein", "employee_ssn", mode="before")
    @classmethod
    def format_tax_id(cls, v: Optional[str]) -> Optional[str]:
        """Format tax ID numbers."""
        if v is None:
            return v
        # Remove any non-digit characters
        digits = "".join(c for c in v if c.isdigit())
        # Format based on length
        if len(digits) == 9:
            return f"{digits[:2]}-{digits[2:]}"
        elif len(digits) == 7:
            return f"{digits[:2]}-{digits[2:]}"
        return v


class StateInfo(BaseModel):
    """State tax withheld information for 1099 forms."""
    
    state: str
    state_id: Optional[str] = None
    state_tax_withheld: Optional[Decimal] = Field(None, decimal_places=2)
    
    class Config:
        json_encoders = {Decimal: str}


class Form1099INT(BaseModel):
    """1099-INT form extracted data."""
    
    id: Optional[int] = None
    document_id: int
    
    # Payer Information
    payer_name: str
    payer_address: Optional[str] = None
    payer_tin: Optional[str] = None
    
    # Recipient Information
    recipient_name: str
    recipient_tin: Optional[str] = None
    recipient_address: Optional[str] = None
    
    # Interest Income
    interest_income: Decimal = Field(..., decimal_places=2)
    early_withdrawal_penalty: Optional[Decimal] = Field(None, decimal_places=2)
    interest_on_us_savings_bonds: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Tax Withheld
    federal_income_tax_withheld: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Additional Information
    investment_expenses: Optional[Decimal] = Field(None, decimal_places=2)
    foreign_tax_paid: Optional[Decimal] = Field(None, decimal_places=2)
    foreign_country: Optional[str] = None
    
    # Tax-Exempt Interest
    tax_exempt_interest: Optional[Decimal] = Field(None, decimal_places=2)
    specified_private_activity_bond_interest: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Bond Premium
    market_discount: Optional[Decimal] = Field(None, decimal_places=2)
    bond_premium: Optional[Decimal] = Field(None, decimal_places=2)
    bond_premium_treasury_obligations: Optional[Decimal] = Field(None, decimal_places=2)
    bond_premium_tax_exempt_bond: Optional[Decimal] = Field(None, decimal_places=2)
    
    # CUSIP
    tax_exempt_cusip_number: Optional[str] = None
    
    # State Information
    state_info: list[StateInfo] = Field(default_factory=list)
    
    # Raw extracted data (JSON)
    raw_data: Optional[dict[str, Any]] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True
        json_encoders = {Decimal: str}


class Form1099DIV(BaseModel):
    """1099-DIV form extracted data."""
    
    id: Optional[int] = None
    document_id: int
    
    # Payer Information
    payer_name: str
    payer_address: Optional[str] = None
    payer_tin: Optional[str] = None
    
    # Recipient Information
    recipient_name: str
    recipient_tin: Optional[str] = None
    recipient_address: Optional[str] = None
    
    # Dividends
    total_ordinary_dividends: Decimal = Field(..., decimal_places=2)
    qualified_dividends: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Capital Gains
    total_capital_gain: Optional[Decimal] = Field(None, decimal_places=2)
    unrecaptured_section_1250_gain: Optional[Decimal] = Field(None, decimal_places=2)
    section_1202_gain: Optional[Decimal] = Field(None, decimal_places=2)
    collectibles_gain: Optional[Decimal] = Field(None, decimal_places=2)
    section_897_ordinary_dividends: Optional[Decimal] = Field(None, decimal_places=2)
    section_897_capital_gain: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Other Distributions
    nondividend_distributions: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Tax Withheld
    federal_income_tax_withheld: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Section 199A
    section_199a_dividends: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Investment Expenses
    investment_expenses: Optional[Decimal] = Field(None, decimal_places=2)
    
    # Foreign Tax
    foreign_tax_paid: Optional[Decimal] = Field(None, decimal_places=2)
    foreign_country: Optional[str] = None
    
    # Liquidation Distributions
    cash_liquidation: Optional[Decimal] = Field(None, decimal_places=2)
    noncash_liquidation: Optional[Decimal] = Field(None, decimal_places=2)
    
    # FATCA
    fatca_filing: bool = False
    
    # State Information
    state_info: list[StateInfo] = Field(default_factory=list)
    
    # Raw extracted data (JSON)
    raw_data: Optional[dict[str, Any]] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True
        json_encoders = {Decimal: str}


# Type alias for any form data
FormData = W2Data | Form1099INT | Form1099DIV