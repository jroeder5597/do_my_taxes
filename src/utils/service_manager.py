"""
Service manager for auto-starting required services (PDFPlumber Tax, Qdrant, Ollama, SearXNG).
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)


class ServiceManager:
    """Manages auto-start of PDFPlumber Tax, Qdrant, Ollama, and SearXNG services."""
    
    def __init__(self):
        self.services_status = {}
    
    def ensure_all_services(self, console=None) -> dict:
        status = {
            "pdfplumber_tax": self._ensure_pdfplumber_tax_service(console),
            "tesseract": self._ensure_tesseract_service(console),
            "qdrant": self._ensure_qdrant_service(console),
            "ollama": self._ensure_ollama_service(console),
            "searxng": self._ensure_searxng_service(console),
        }
        self.services_status = status
        return status
    
    def _ensure_pdfplumber_tax_service(self, console=None) -> bool:
        try:
            from src.ocr.pdfplumber_tax_manager import PDFPlumberTaxPodmanManager
            
            pdfplumber_tax_manager = PDFPlumberTaxPodmanManager()
            
            if pdfplumber_tax_manager.is_container_running():
                if console:
                    console.print("[green]PDFPlumber Tax service already running[/green]")
                return True
            
            if not pdfplumber_tax_manager.is_image_built():
                if console:
                    console.print("[blue]Building PDFPlumber Tax image (this may take a few minutes)...[/blue]")
                if not pdfplumber_tax_manager.build_image():
                    if console:
                        console.print("[red]Failed to build PDFPlumber Tax image[/red]")
                    return False
                if console:
                    console.print("[green]PDFPlumber Tax image built successfully[/green]")
            
            if pdfplumber_tax_manager.start_container():
                if console:
                    console.print("[green]PDFPlumber Tax service started[/green]")
                return True
            
            if console:
                console.print("[red]Failed to start PDFPlumber Tax service[/red]")
            return False
        except Exception as e:
            logger.debug(f"PDFPlumber Tax service not available: {e}")
            if console:
                console.print(f"[yellow]PDFPlumber Tax service error: {e}[/yellow]")
            return False
    
    def _ensure_tesseract_service(self, console=None) -> bool:
        try:
            from src.ocr.tesseract_manager import TesseractPodmanManager
            
            tesseract_manager = TesseractPodmanManager()
            
            if tesseract_manager.is_container_running():
                if tesseract_manager.is_service_healthy():
                    if console:
                        console.print("[green]Tesseract service already running[/green]")
                    return True
                else:
                    tesseract_manager.remove_container()
            
            if not tesseract_manager.is_image_built():
                if console:
                    console.print("[blue]Building Tesseract image...[/blue]")
                if not tesseract_manager.build_image():
                    if console:
                        console.print("[red]Failed to build Tesseract image[/red]")
                    return False
            
            if tesseract_manager.start_container():
                if console:
                    console.print("[green]Tesseract service started[/green]")
                return True
            
            if console:
                console.print("[red]Failed to start Tesseract service[/red]")
            return False
        except Exception as e:
            logger.debug(f"Tesseract service not available: {e}")
            if console:
                console.print(f"[yellow]Tesseract service error: {e}[/yellow]")
            return False
    
    def _ensure_qdrant_service(self, console=None) -> bool:
        try:
            from src.storage.qdrant_manager import QdrantManager
            
            qdrant_manager = QdrantManager()
            if qdrant_manager.is_container_running():
                return True
            
            if qdrant_manager.ensure_service_running(auto_pull=True):
                if console:
                    console.print("[green]Qdrant service started[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Qdrant service not available: {e}")
            return False
    
    def _ensure_ollama_service(self, console=None) -> bool:
        from src.utils.config import get_settings
        
        try:
            settings = get_settings()
            ollama_url = settings.llm.ollama.base_url
            
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
        try:
            from src.web.searxng_manager import SearXNGManager
            from src.utils.config import get_settings
            
            settings = get_settings()
            if not settings.web_search.enabled:
                logger.debug("Web search is disabled in configuration")
                return False
            
            searxng_manager = SearXNGManager(port=settings.web_search.searxng.port)
            if searxng_manager.is_container_running():
                if console:
                    console.print("[green]SearXNG service running[/green]")
                return True
            
            if searxng_manager.ensure_service_running(auto_pull=True):
                if console:
                    console.print("[green]SearXNG service started[/green]")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"SearXNG service not available: {e}")
            return False
    
    def get_status_summary(self) -> str:
        if not self.services_status:
            return "Services not checked"
        
        parts = []
        if self.services_status.get("pdfplumber_tax"):
            parts.append("PDFPlumber Tax")
        if self.services_status.get("tesseract"):
            parts.append("Tesseract")
        if self.services_status.get("qdrant"):
            parts.append("Qdrant")
        if self.services_status.get("ollama"):
            parts.append("Ollama")
        if self.services_status.get("searxng"):
            parts.append("SearXNG")
        
        if not parts:
            return "No services running"
        
        return ", ".join(parts)


def ensure_services(console=None) -> dict:
    manager = ServiceManager()
    return manager.ensure_all_services(console)
