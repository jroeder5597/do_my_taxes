"""
Document classifier module.
Identifies tax document types (W2, 1099-INT, 1099-DIV, etc.) from OCR text.
"""

import json
import re
from pathlib import Path
from typing import Optional

from src.storage.models import DocumentType
from src.utils import get_logger

logger = get_logger(__name__)


class DocumentClassifier:
    """
    Classify tax documents based on OCR text content.
    Uses pattern matching and keyword analysis.
    """
    
    # Document type patterns
    DOCUMENT_PATTERNS = {
        DocumentType.W2: [
            r"\bW-?2\b",
            r"Wage\s+and\s+Tax\s+Statement",
            r"Form\s+W-?2",
            r"Box\s+1.*Wages",
            r"Box\s+2.*Federal\s+income\s+tax\s+withheld",
            r"Social\s+security\s+wages",
            r"Medicare\s+wages",
        ],
        DocumentType.FORM_1099_INT: [
            r"\b1099-?INT\b",
            r"Form\s+1099-?INT",
            r"Interest\s+Income",
            r"Payer's\s+name.*interest",
            r"Box\s+1.*Interest\s+income",
            r"Box\s+4.*Federal\s+income\s+tax\s+withheld",
        ],
        DocumentType.FORM_1099_DIV: [
            r"\b1099-?DIV\b",
            r"Form\s+1099-?DIV",
            r"Dividends\s+and\s+Distributions",
            r"Total\s+ordinary\s+dividends",
            r"Qualified\s+dividends",
            r"Box\s+1a.*Total\s+ordinary\s+dividends",
        ],
        DocumentType.FORM_1099_B: [
            r"\b1099-?B\b",
            r"Form\s+1099-?B",
            r"Proceeds\s+from\s+Broker",
            r"Barter\s+Exchange",
        ],
        DocumentType.FORM_1099_NEC: [
            r"\b1099-?NEC\b",
            r"Form\s+1099-?NEC",
            r"Nonemployee\s+Compensation",
        ],
        DocumentType.FORM_1099_G: [
            r"\b1099-?G\b",
            r"Form\s+1099-?G",
            r"Certain\s+Government\s+Payments",
            r"Unemployment\s+compensation",
        ],
        DocumentType.FORM_1099_R: [
            r"\b1099-?R\b",
            r"Form\s+1099-?R",
            r"Distributions\s+from\s+Pensions",
            r"Annuities\s+Retirement",
        ],
        DocumentType.FORM_1098: [
            r"\b1098\b",
            r"Form\s+1098",
            r"Mortgage\s+Interest\s+Statement",
        ],
    }
    
    # Keywords that strengthen classification confidence
    CONFIDENCE_KEYWORDS = {
        DocumentType.W2: [
            "employer", "employee", "ein", "ssn", "wages", "withheld",
            "social security", "medicare", "box 12", "box 14",
        ],
        DocumentType.FORM_1099_INT: [
            "interest", "payer", "recipient", "bond", "treasury",
            "tax-exempt", "investment", "penalty",
        ],
        DocumentType.FORM_1099_DIV: [
            "dividend", "capital gain", "qualified", "ordinary",
            "section 199a", "foreign tax", "liquidation",
        ],
    }
    
    def __init__(self):
        """Initialize the document classifier."""
        pass
    
    def classify(self, text: str) -> tuple[DocumentType, float]:
        """
        Classify a document based on its OCR text.
        
        Args:
            text: OCR text from the document
        
        Returns:
            Tuple of (document_type, confidence_score)
        """
        if not text or not text.strip():
            return DocumentType.UNKNOWN, 0.0
        
        text_lower = text.lower()
        
        # Score each document type
        scores: dict[DocumentType, float] = {}
        
        for doc_type, patterns in self.DOCUMENT_PATTERNS.items():
            score = self._calculate_score(text, text_lower, doc_type, patterns)
            scores[doc_type] = score
        
        # Find the best match
        if not scores:
            return DocumentType.UNKNOWN, 0.0
        
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        
        # Require minimum confidence
        if best_score < 0.3:
            logger.warning(f"Low confidence classification: {best_type.value} ({best_score:.2f})")
            return DocumentType.OTHER, best_score
        
        logger.info(f"Classified as {best_type.value} with confidence {best_score:.2f}")
        return best_type, best_score
    
    def _calculate_score(
        self,
        text: str,
        text_lower: str,
        doc_type: DocumentType,
        patterns: list[str],
    ) -> float:
        """
        Calculate classification score for a document type.
        
        Args:
            text: Original OCR text
            text_lower: Lowercase OCR text
            doc_type: Document type being scored
            patterns: Regex patterns for this document type
        
        Returns:
            Confidence score (0.0 to 1.0)
        """
        score = 0.0
        
        # Pattern matching (case-insensitive)
        pattern_matches = 0
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                pattern_matches += 1
        
        # Pattern score (weighted heavily)
        if patterns:
            pattern_score = pattern_matches / len(patterns)
            score += pattern_score * 0.7
        
        # Keyword matching
        keywords = self.CONFIDENCE_KEYWORDS.get(doc_type, [])
        if keywords:
            keyword_matches = sum(1 for kw in keywords if kw in text_lower)
            keyword_score = keyword_matches / len(keywords)
            score += keyword_score * 0.3
        
        return min(score, 1.0)  # Cap at 1.0
    
    def classify_file(self, file_path: str | Path, text: Optional[str] = None) -> tuple[DocumentType, float]:
        """
        Classify a document file.
        
        Args:
            file_path: Path to the document file
            text: Optional pre-extracted OCR text
        
        Returns:
            Tuple of (document_type, confidence_score)
        """
        path = Path(file_path)
        
        # Check filename for hints
        filename_type = self._classify_by_filename(path.name)
        
        if text:
            text_type, text_confidence = self.classify(text)
            
            # If filename gives a strong hint, use it
            if filename_type != DocumentType.UNKNOWN and text_confidence < 0.5:
                return filename_type, 0.8
            
            return text_type, text_confidence
        
        # Fall back to filename classification
        return filename_type, 0.6 if filename_type != DocumentType.UNKNOWN else 0.0
    
    def _classify_by_filename(self, filename: str) -> DocumentType:
        """
        Classify document based on filename.
        
        Args:
            filename: Document filename
        
        Returns:
            Document type
        """
        filename_lower = filename.lower()
        
        if re.search(r"\bw-?2\b", filename_lower):
            return DocumentType.W2
        elif re.search(r"1099-?int", filename_lower):
            return DocumentType.FORM_1099_INT
        elif re.search(r"1099-?div", filename_lower):
            return DocumentType.FORM_1099_DIV
        elif re.search(r"1099-?b\b", filename_lower):
            return DocumentType.FORM_1099_B
        elif re.search(r"1099-?nec", filename_lower):
            return DocumentType.FORM_1099_NEC
        elif re.search(r"1099-?g\b", filename_lower):
            return DocumentType.FORM_1099_G
        elif re.search(r"1099-?r\b", filename_lower):
            return DocumentType.FORM_1099_R
        elif re.search(r"1098\b", filename_lower):
            return DocumentType.FORM_1098
        
        return DocumentType.UNKNOWN
    
    def get_document_info(self, text: str) -> dict:
        """
        Get detailed classification information for a document.
        
        Args:
            text: OCR text from the document
        
        Returns:
            Dictionary with classification details
        """
        doc_type, confidence = self.classify(text)
        
        # Get all scores
        text_lower = text.lower()
        all_scores = {}
        
        for dt, patterns in self.DOCUMENT_PATTERNS.items():
            score = self._calculate_score(text, text_lower, dt, patterns)
            all_scores[dt.value] = round(score, 3)
        
        return {
            "document_type": doc_type.value,
            "confidence": round(confidence, 3),
            "all_scores": all_scores,
            "text_length": len(text),
            "word_count": len(text.split()),
        }