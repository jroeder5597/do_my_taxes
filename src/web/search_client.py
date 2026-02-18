"""
Web search client with PII protection for tax assistance.

CRITICAL: This module enforces strict PII (Personally Identifiable Information)
protection. Under NO circumstances should any personal tax document information
be included in web searches. This includes:
- User's name
- Social Security Numbers (SSN)
- Employer names
- Addresses
- Financial account numbers
- Any other personal information

Web searches are ONLY for general tax guidance and regulations.
"""

import re
from dataclasses import dataclass
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)


class PIIDetectionError(Exception):
    """Raised when PII is detected in a search query."""
    pass


@dataclass
class SearchResult:
    """A single search result from SearXNG."""
    title: str
    url: str
    content: str
    engine: str


class PIIGuard:
    """
    Guards against PII leakage in search queries.
    
    This class implements multiple layers of PII detection to ensure
    that no personal information is ever sent to external search engines.
    """
    
    # SSN patterns (XXX-XX-XXXX or XXXXXXXXX)
    SSN_PATTERN = re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b')
    
    # EIN patterns (XX-XXXXXXX)
    EIN_PATTERN = re.compile(r'\b\d{2}[-\s]?\d{7}\b')
    
    # Credit card-like patterns (groups of 4 digits)
    CC_PATTERN = re.compile(r'\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b')
    
    # Bank account patterns (8-17 consecutive digits often preceded by routing)
    ACCOUNT_PATTERN = re.compile(r'\b\d{8,17}\b')
    
    # Phone number patterns
    PHONE_PATTERN = re.compile(r'\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
    
    # Email patterns
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    
    # Address indicators (street, avenue, etc. with numbers)
    ADDRESS_PATTERN = re.compile(
        r'\b\d+\s+(street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|way|court|ct|place|pl)\b',
        re.IGNORECASE
    )
    
    # Common name patterns (first last format with capital letters)
    # This is a heuristic - we look for "My name is", "I am", etc.
    NAME_CONTEXT_PATTERN = re.compile(
        r'\b(my name is|i am|i\'m|my employer is|employer:|worked for)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b',
        re.IGNORECASE
    )
    
    # Employer-specific patterns
    EMPLOYER_PATTERN = re.compile(
        r'\b(employer|company|worked at|working for|my job at)\s*[:\s]+[A-Z][a-zA-Z\s&.,]+\b',
        re.IGNORECASE
    )
    
    # Financial amounts that might indicate personal data
    # (large dollar amounts with specific context)
    PERSONAL_AMOUNT_PATTERN = re.compile(
        r'\b(my (wage|salary|income|bonus) is|earned|made|paid)\s*\$?\d{1,3}(,\d{3})*(\.\d{2})?\b',
        re.IGNORECASE
    )
    
    # Specific tax form numbers that might contain personal data
    TAX_FORM_PERSONAL_PATTERN = re.compile(
        r'\b(w-2|1099|1040|schedule)\s*(box|line)?\s*\d*\s*(is|shows|says|has)\s*[A-Z][a-z]+\b',
        re.IGNORECASE
    )
    
    @classmethod
    def detect_pii(cls, query: str) -> list[str]:
        """
        Detect potential PII in a search query.
        
        Args:
            query: The search query to check
            
        Returns:
            List of detected PII types (empty if none detected)
        """
        detected = []
        
        if cls.SSN_PATTERN.search(query):
            detected.append("Social Security Number")
        
        if cls.EIN_PATTERN.search(query):
            detected.append("Employer Identification Number")
        
        if cls.CC_PATTERN.search(query):
            detected.append("Credit Card Number")
        
        if cls.PHONE_PATTERN.search(query):
            detected.append("Phone Number")
        
        if cls.EMAIL_PATTERN.search(query):
            detected.append("Email Address")
        
        if cls.ADDRESS_PATTERN.search(query):
            detected.append("Street Address")
        
        if cls.NAME_CONTEXT_PATTERN.search(query):
            detected.append("Personal Name")
        
        if cls.EMPLOYER_PATTERN.search(query):
            detected.append("Employer Name")
        
        if cls.PERSONAL_AMOUNT_PATTERN.search(query):
            detected.append("Personal Financial Amount")
        
        if cls.TAX_FORM_PERSONAL_PATTERN.search(query):
            detected.append("Personal Tax Form Data")
        
        # Check for account numbers only if they appear in a suspicious context
        # (not just random numbers like years or zip codes)
        account_matches = cls.ACCOUNT_PATTERN.findall(query)
        for match in account_matches:
            # Skip if it looks like a year (1900-2099) or zip code (5 digits)
            if len(match) == 4 and match.startswith(('19', '20')):
                continue
            if len(match) == 5 and match.isdigit():
                continue
            detected.append("Account Number")
            break
        
        return detected
    
    @classmethod
    def sanitize_query(cls, query: str) -> str:
        """
        Attempt to sanitize a query by removing detected PII.
        
        WARNING: This is a fallback mechanism. The recommended approach
        is to reject queries containing PII entirely.
        
        Args:
            query: The query to sanitize
            
        Returns:
            Sanitized query with PII removed
        """
        sanitized = query
        
        # Remove detected PII patterns
        sanitized = cls.SSN_PATTERN.sub("[REDACTED_SSN]", sanitized)
        sanitized = cls.EIN_PATTERN.sub("[REDACTED_EIN]", sanitized)
        sanitized = cls.CC_PATTERN.sub("[REDACTED_CC]", sanitized)
        sanitized = cls.PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)
        sanitized = cls.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)
        sanitized = cls.ADDRESS_PATTERN.sub("[REDACTED_ADDRESS]", sanitized)
        
        return sanitized
    
    @classmethod
    def validate_query(cls, query: str) -> tuple[bool, list[str]]:
        """
        Validate that a query is safe to send to external search.
        
        Args:
            query: The search query to validate
            
        Returns:
            Tuple of (is_safe, detected_pii_list)
        """
        detected = cls.detect_pii(query)
        return len(detected) == 0, detected


class WebSearchClient:
    """
    Client for performing web searches via SearXNG with PII protection.
    
    IMPORTANT: This client enforces strict PII protection. Any query
    containing personal information will be rejected immediately.
    """
    
    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 10):
        """
        Initialize the web search client.
        
        Args:
            base_url: URL of the SearXNG service
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.pii_guard = PIIGuard()
    
    def search(self, query: str, engines: Optional[list[str]] = None, 
               max_results: int = 5) -> list[SearchResult]:
        """
        Execute a web search with PII protection.
        
        CRITICAL: This method will raise PIIDetectionError if any PII
        is detected in the query. The search will NOT be executed.
        
        Args:
            query: Search query (MUST NOT contain any PII)
            engines: List of search engines to use (default: all)
            max_results: Maximum number of results to return
            
        Returns:
            List of SearchResult objects
            
        Raises:
            PIIDetectionError: If PII is detected in the query
            requests.RequestException: If search request fails
        """
        # CRITICAL: Validate query for PII before proceeding
        is_safe, detected_pii = self.pii_guard.validate_query(query)
        
        if not is_safe:
            logger.error(f"PII DETECTED in search query: {detected_pii}")
            logger.error(f"Query rejected: {query}")
            raise PIIDetectionError(
                f"Search query contains PII and has been BLOCKED. "
                f"Detected: {', '.join(detected_pii)}. "
                f"Web searches must NOT contain personal information. "
                f"Only general tax guidance queries are permitted."
            )
        
        # Log the safe query for audit purposes
        logger.info(f"Executing safe web search: {query}")
        
        # Build search URL
        params = {
            "q": query,
            "format": "json",
        }
        
        if engines:
            params["engines"] = ",".join(engines)
        
        try:
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for item in data.get("results", [])[:max_results]:
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    engine=item.get("engine", "unknown"),
                ))
            
            logger.info(f"Web search returned {len(results)} results")
            return results
            
        except requests.RequestException as e:
            logger.error(f"Web search request failed: {e}")
            raise
    
    def search_tax_guidance(self, query: str, tax_year: int,
                            jurisdiction: Optional[str] = None) -> list[SearchResult]:
        """
        Search for general tax guidance with automatic query enrichment.
        
        This method adds tax context to queries while ensuring no PII is included.
        It's designed for searching general tax rules, regulations, and guidance.
        
        Args:
            query: Tax-related query (MUST be general, no PII)
            tax_year: Tax year for context
            jurisdiction: Optional jurisdiction (federal, state code like 'ca', 'az')
            
        Returns:
            List of SearchResult objects
            
        Raises:
            PIIDetectionError: If PII is detected in the query
        """
        # Build enriched query for tax context
        context_parts = []
        
        # Add tax year
        context_parts.append(f"{tax_year}")
        
        # Add jurisdiction context
        if jurisdiction:
            jurisdiction_names = {
                "federal": "IRS federal",
                "ca": "California",
                "az": "Arizona",
            }
            context_name = jurisdiction_names.get(jurisdiction.lower(), jurisdiction.upper())
            context_parts.append(context_name)
        
        # Build the final query
        enriched_query = f"{' '.join(context_parts)} {query} tax guidance"
        
        # Validate the enriched query (belt and suspenders)
        is_safe, detected_pii = self.pii_guard.validate_query(enriched_query)
        
        if not is_safe:
            logger.error(f"PII DETECTED in enriched search query: {detected_pii}")
            logger.error(f"Original query: {query}")
            logger.error(f"Enriched query: {enriched_query}")
            raise PIIDetectionError(
                f"Search query contains PII and has been BLOCKED. "
                f"Detected: {', '.join(detected_pii)}. "
                f"Please rephrase your question using only general terms."
            )
        
        return self.search(enriched_query, max_results=5)
    
    def is_service_available(self) -> bool:
        """Check if the SearXNG service is available."""
        try:
            response = requests.get(
                f"{self.base_url}/healthz",
                timeout=5,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False


def create_search_client() -> Optional[WebSearchClient]:
    """
    Create a web search client if the service is available.
    
    Returns:
        WebSearchClient instance or None if service unavailable
    """
    try:
        from src.utils.config import get_settings
        
        settings = get_settings()
        
        if not settings.web_search.enabled:
            logger.debug("Web search is disabled in configuration")
            return None
        
        client = WebSearchClient(
            base_url=f"http://{settings.web_search.searxng.host}:{settings.web_search.searxng.port}",
            timeout=settings.web_search.searxng.timeout,
        )
        
        if client.is_service_available():
            logger.info("Web search service is available")
            return client
        else:
            logger.warning("Web search service is not available")
            return None
            
    except Exception as e:
        logger.debug(f"Could not create web search client: {e}")
        return None