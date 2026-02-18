"""
Service manager for auto-starting required services (OCR, Qdrant, Ollama, SearXNG).
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)


class ServiceManager:
    """Manages auto-start of OCR, Qdrant, Ollama, and SearXNG services."""
    
    def __init__(self):
        self.services_status = {}
    
    def ensure_all_services(self, console=None) -> dict:
        """
        Ensure all required services are running.
        
        Returns:
            Dictionary with status of each service
        """
        status = {
            "ocr": self._ensure_ocr_service(console),
            "qdrant": self._ensure_qdrant_service(console),
            "ollama": self._ensure_ollama_service(console),
            "searxng": self._ensure_searxng_service(console),
        }
        self.services_status = status
        return status
    
    def _ensure_ocr_service(self, console=None) -> bool:
        """Ensure OCR service is running."""
        try:
            from src.storage.qdrant_manager import QdrantManager
            from src.ocr.docker_manager import PodmanManager
            
            # Check if already running
            ocr_manager = PodmanManager()
            if ocr_manager.is_container_running():
                return True
            
            # Try to start it
            if ocr_manager.ensure_service_running(auto_build=False):
                if console:
                    console.print("[green]OCR service started[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"OCR service not available: {e}")
            return False
    
    def _ensure_qdrant_service(self, console=None) -> bool:
        """Ensure Qdrant service is running."""
        try:
            from src.storage.qdrant_manager import QdrantManager
            
            # Check if already running
            qdrant_manager = QdrantManager()
            if qdrant_manager.is_container_running():
                return True
            
            # Try to start it
            if qdrant_manager.ensure_service_running(auto_pull=True):
                if console:
                    console.print("[green]Qdrant service started[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Qdrant service not available: {e}")
            return False
    
    def _ensure_ollama_service(self, console=None) -> bool:
        """Ensure Ollama service is running and accessible."""
        from src.utils.config import get_settings
        
        try:
            settings = get_settings()
            ollama_url = settings.llm.ollama.base_url
            
            # Check if Ollama is accessible
            response = requests.get(f"{ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                if console:
                    console.print("[green]Ollama service accessible[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Ollama service not accessible: {e}")
            if console:
                console.print("[yellow]Ollama not accessible - some features may be limited[/yellow]")
            return False
    
    def _ensure_searxng_service(self, console=None) -> bool:
        """
        Ensure SearXNG service is running.
        
        SearXNG is a privacy-respecting metasearch engine used for
        web search fallback when local tax guidance is insufficient.
        
        IMPORTANT: Web searches are ONLY for general tax guidance.
        NO personal information is ever sent to search engines.
        """
        try:
            from src.web.searxng_manager import SearXNGManager
            from src.utils.config import get_settings
            
            # Check if web search is enabled
            settings = get_settings()
            if not settings.web_search.enabled:
                logger.debug("Web search is disabled in configuration")
                return False
            
            # Check if already running
            searxng_manager = SearXNGManager(port=settings.web_search.searxng.port)
            if searxng_manager.is_container_running():
                if console:
                    console.print("[green]SearXNG service running[/green]")
                return True
            
            # Try to start it
            if searxng_manager.ensure_service_running(auto_pull=True):
                if console:
                    console.print("[green]SearXNG service started[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"SearXNG service not available: {e}")
            return False
    
    def get_status_summary(self) -> str:
        """Get a summary of service status."""
        if not self.services_status:
            return "Services not checked"
        
        parts = []
        if self.services_status.get("ocr"):
            parts.append("OCR")
        if self.services_status.get("qdrant"):
            parts.append("Qdrant")
        if self.services_status.get("ollama"):
            parts.append("Ollama")
        if self.services_status.get("searxng"):
            parts.append("SearXNG")
        
        if not parts:
            return "No services running"
        
        return ", ".join(parts)


# Convenience function
def ensure_services(console=None) -> dict:
    """Ensure all services are running."""
    manager = ServiceManager()
    return manager.ensure_all_services(console)
