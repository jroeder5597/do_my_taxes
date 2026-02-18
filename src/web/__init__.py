"""
Web search module for tax assistance.

Provides privacy-focused web search capabilities via SearXNG for
general tax guidance when local documents are insufficient.

CRITICAL: This module enforces strict PII protection. No personal
information from tax documents is ever sent to external search engines.
"""

from src.web.searxng_manager import (
    SearXNGManager,
    ensure_searxng_service,
    get_searxng_status,
)
from src.web.search_client import (
    WebSearchClient,
    SearchResult,
    PIIGuard,
    PIIDetectionError,
    create_search_client,
)

__all__ = [
    # SearXNG container management
    "SearXNGManager",
    "ensure_searxng_service",
    "get_searxng_status",
    # Web search client
    "WebSearchClient",
    "SearchResult",
    "PIIGuard",
    "PIIDetectionError",
    "create_search_client",
]