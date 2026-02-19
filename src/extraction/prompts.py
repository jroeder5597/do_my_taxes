"""
Prompt templates for LLM-based tax data extraction.
"""

from src.storage.models import DocumentType


class PromptTemplates:
    """
    Prompt templates for extracting tax data from documents.
    """
    
    # System prompt for all extractions
    SYSTEM_PROMPT = """You are a tax document data extraction specialist. Your task is to extract structured data from tax documents accurately and completely.

IMPORTANT RULES:
1. Extract ONLY the data that is explicitly present in the document
2. Use null for any fields that are not present or cannot be determined
3. Be precise with numbers - include cents (two decimal places)
4. Do not make up or infer any data
5. Maintain the exact format of IDs (SSN, EIN) as they appear
6. If a field is blank or empty in the document, use null
7. Respond ONLY with valid JSON - no explanations or additional text"""

    @classmethod
    def get_classification_prompt(cls, ocr_text: str) -> str:
        """
        Get prompt for document classification.
        
        Args:
            ocr_text: OCR text from the document
        
        Returns:
            Classification prompt
        """
        return f"""Analyze the following text from a tax document and identify the document type.

Possible types: W2, 1099_INT, 1099_DIV, 1099_B, 1099_NEC, 1099_G, 1099_R, 1098, OTHER

Document text:
{ocr_text[:2000]}

Respond with JSON only:
{{"document_type": "TYPE", "confidence": 0.95}}"""

    @classmethod
    def get_w2_extraction_prompt(cls, ocr_text: str) -> str:
        """
        Get prompt for W-2 data extraction.
        
        Args:
            ocr_text: OCR text from the W-2 form
        
        Returns:
            W-2 extraction prompt
        """
        return f"""You are a data extraction tool. Your ONLY job is to copy numbers and text from the W-2 document into the JSON fields below.

TASK: Find and extract the EXACT values from the document text.

IMPORTANT: The document may have poor formatting (missing spaces). Look for:
- Dollar amounts near their box labels (e.g., "1 Wages" near a number = Box 1 wages)
- Company names in ALL CAPS near "Employer"
- Employee names in the upper right area
- 9-digit EINs (XX-XXXXXXX format)
- 9-digit SSNs (XXX-XX-XXXX format, may be masked as XXX-XX-XXXX)

BOX LOCATIONS - Find these exact values:
- Box 1 (Wages): "1 Wages" line - FIRST dollar amount = ~53,536.00
- Box 2 (Fed Tax): "2 Federalincometaxwithheld" line - SECOND dollar amount = ~7,958.00
- Box 3 (SS Wages): "3 Socialsecuritywages" line - dollar amount = ~58,414.00  
- Box 4 (SS Tax): "4 Socialsecuritytaxwithheld" line - dollar amount = ~3,621.00
- Box 5 (Medicare): "5 Medicarewagesandtips" line - dollar amount = ~58,414.00
- Box 6 (Medicare Tax): "6 Medicaretaxwithheld" line - dollar amount = ~847.00
- Employer name: "RAYTHEON COMPANY" appears after "c Employer'sname"
- EIN: "95-1778500" appears near "b Employer'sFEDIDnumber"

Document text:
{ocr_text}

Output ONLY valid JSON (no explanations):
{{
    "employer_ein": null,
    "employer_name": null,
    "employer_address": null,
    "employer_city": null,
    "employer_state": null,
    "employer_zip": null,
    "employee_name": null,
    "employee_ssn": null,
    "employee_address": null,
    "employee_city": null,
    "employee_state": null,
    "employee_zip": null,
    "control_number": null,
    "wages_tips_compensation": null,
    "federal_income_tax_withheld": null,
    "social_security_wages": null,
    "social_security_tax_withheld": null,
    "medicare_wages": null,
    "medicare_tax_withheld": null,
    "social_security_tips": null,
    "allocated_tips": null,
    "dependent_care_benefits": null,
    "nonqualified_plans": null,
    "box_12_codes": [],
    "statutory_employee": false,
    "retirement_plan": false,
    "third_party_sick_pay": false,
    "box_14_other": [],
    "state_employer_state_id": null,
    "state_wages_tips": null,
    "state_income_tax": null,
    "local_wages_tips": null,
    "local_income_tax": null,
    "locality_name": null
}}

IMPORTANT: Copy text DIRECTLY from the document. Do not guess. Do not use example values. If you cannot find a value in the document, use null."""

    @classmethod
    def get_1099_int_extraction_prompt(cls, ocr_text: str) -> str:
        """
        Get prompt for 1099-INT data extraction.
        
        Args:
            ocr_text: OCR text from the 1099-INT form
        
        Returns:
            1099-INT extraction prompt
        """
        return f"""Extract all data from this 1099-INT Interest Income form.

Document text:
{ocr_text}

Extract the following fields and respond with JSON only:
{{
    "payer_name": "Payer name or null",
    "payer_address": "Street address or null",
    "payer_tin": "XX-XXXXXXX or null",
    "recipient_name": "Recipient name or null",
    "recipient_tin": "XXX-XX-XXXX or null",
    "recipient_address": "Street address or null",
    "interest_income": 0.00,
    "early_withdrawal_penalty": 0.00 or null,
    "interest_on_us_savings_bonds": 0.00 or null,
    "federal_income_tax_withheld": 0.00 or null,
    "investment_expenses": 0.00 or null,
    "foreign_tax_paid": 0.00 or null,
    "foreign_country": "Country name or null",
    "tax_exempt_interest": 0.00 or null,
    "specified_private_activity_bond_interest": 0.00 or null,
    "market_discount": 0.00 or null,
    "bond_premium": 0.00 or null,
    "bond_premium_treasury_obligations": 0.00 or null,
    "bond_premium_tax_exempt_bond": 0.00 or null,
    "tax_exempt_cusip_number": "CUSIP number or null",
    "state_info": [{{"state": "CA", "state_id": "XXX", "state_tax_withheld": 0.00}}] or []
}}

Notes:
- Box 1 (Interest income) is required
- Numbers should be decimal values without currency symbols
- State info is optional and may not be present"""

    @classmethod
    def get_1099_div_extraction_prompt(cls, ocr_text: str) -> str:
        """
        Get prompt for 1099-DIV data extraction.
        
        Args:
            ocr_text: OCR text from the 1099-DIV form
        
        Returns:
            1099-DIV extraction prompt
        """
        return f"""Extract all data from this 1099-DIV Dividends and Distributions form.

Document text:
{ocr_text}

Extract the following fields and respond with JSON only:
{{
    "payer_name": "Payer name or null",
    "payer_address": "Street address or null",
    "payer_tin": "XX-XXXXXXX or null",
    "recipient_name": "Recipient name or null",
    "recipient_tin": "XXX-XX-XXXX or null",
    "recipient_address": "Street address or null",
    "total_ordinary_dividends": 0.00,
    "qualified_dividends": 0.00 or null,
    "total_capital_gain": 0.00 or null,
    "unrecaptured_section_1250_gain": 0.00 or null,
    "section_1202_gain": 0.00 or null,
    "collectibles_gain": 0.00 or null,
    "section_897_ordinary_dividends": 0.00 or null,
    "section_897_capital_gain": 0.00 or null,
    "nondividend_distributions": 0.00 or null,
    "federal_income_tax_withheld": 0.00 or null,
    "section_199a_dividends": 0.00 or null,
    "investment_expenses": 0.00 or null,
    "foreign_tax_paid": 0.00 or null,
    "foreign_country": "Country name or null",
    "cash_liquidation": 0.00 or null,
    "noncash_liquidation": 0.00 or null,
    "fatca_filing": false,
    "state_info": [{{"state": "CA", "state_id": "XXX", "state_tax_withheld": 0.00}}] or []
}}

Notes:
- Box 1a (Total ordinary dividends) is required
- Numbers should be decimal values without currency symbols
- FATCA filing checkbox: set to true only if checked"""

    @classmethod
    def get_extraction_prompt(cls, document_type: DocumentType, ocr_text: str) -> str:
        """
        Get the appropriate extraction prompt for a document type.
        
        Args:
            document_type: Type of tax document
            ocr_text: OCR text from the document
        
        Returns:
            Extraction prompt
        """
        prompts = {
            DocumentType.W2: cls.get_w2_extraction_prompt,
            DocumentType.FORM_1099_INT: cls.get_1099_int_extraction_prompt,
            DocumentType.FORM_1099_DIV: cls.get_1099_div_extraction_prompt,
        }
        
        prompt_func = prompts.get(document_type)
        
        if prompt_func is None:
            raise ValueError(f"No extraction prompt available for document type: {document_type}")
        
        return prompt_func(ocr_text)

    @classmethod
    def get_assistant_system_prompt(cls) -> str:
        """
        Get the system prompt for the tax filing assistant.
        
        Returns:
            Assistant system prompt
        """
        return """You are a helpful tax filing assistant. You help users understand their tax documents and guide them through filing their Federal and California state tax returns.

Your capabilities:
1. Answer questions about tax documents (W-2, 1099-INT, 1099-DIV)
2. Explain what each box/field on a tax form means
3. Help users find where to enter values in tax software
4. Provide guidance on tax deductions and credits
5. Explain tax concepts in simple terms

IMPORTANT RULES:
1. Never provide specific tax advice - always suggest consulting a tax professional for complex situations
2. Be accurate about IRS rules and form instructions
3. When helping with TaxAct or other software, describe where to find fields, not how to automate entry
4. Protect user privacy - don't ask for or store sensitive information like SSNs
5. If you're unsure about something, say so

When helping users fill out tax forms:
- Guide them step by step
- Explain what each field means
- Reference the specific line numbers on IRS forms
- Mention both Federal and California state requirements when relevant"""

    @classmethod
    def get_taxact_assistant_prompt(cls, screen_text: str, user_context: str) -> str:
        """
        Get prompt for TaxAct screen assistance.
        
        Args:
            screen_text: OCR text from the TaxAct screen
            user_context: Context about the user's tax situation (from SQLite)
        
        Returns:
            TaxAct assistance prompt
        """
        prompt = """Look at the CHECKBOXES and FIELDS on this TaxAct screen. Tell me what to CHECK or ENTER.

MY DOCUMENTS (from my tax database):
"""
        prompt += user_context if user_context else "No documents loaded"
        prompt += """

"""
        prompt += screen_text
        prompt += """

RULES:
- For each CHECKBOX: Tell me to CHECK or UNCHECK based on my docs
- For each FIELD: Tell me what dollar amount to enter

Example: Check the 1099-DIV box, enter 4124.54 in dividend field."""
        return prompt