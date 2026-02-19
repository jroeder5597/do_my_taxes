"""
Service manager for auto-starting required services (Flyfield, Qdrant, Ollama, SearXNG).
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)


class ServiceManager:
    """Manages auto-start of Flyfield, Qdrant, Ollama, and SearXNG services."""
    
    def __init__(self):
        self.services_status = {}
    
    def ensure_all_services(self, console=None) -> dict:
        status = {
            "flyfield": self._ensure_flyfield_service(console),
            "qdrant": self._ensure_qdrant_service(console),
            "ollama": self._ensure_ollama_service(console),
            "searxng": self._ensure_searxng_service(console),
        }
        self.services_status = status
        return status
    
    def _ensure_flyfield_service(self, console=None) -> bool:
        try:
            from src.ocr.flyfield_manager import FlyfieldPodmanManager
            
            flyfield_manager = FlyfieldPodmanManager()
            
            if flyfield_manager.is_container_running():
                if console:
                    console.print("[green]Flyfield service already running[/green]")
                return True
            
            if not flyfield_manager.is_image_built():
                if console:
                    console.print("[blue]Building Flyfield image (this may take a few minutes)...[/blue]")
                if not flyfield_manager.build_image():
                    if console:
                        console.print("[red]Failed to build Flyfield image[/red]")
                    return False
                if console:
                    console.print("[green]Flyfield image built successfully[/green]")
            
            if flyfield_manager.start_container():
                if console:
                    console.print("[green]Flyfield service started[/green]")
                return True
            
            if console:
                console.print("[red]Failed to start Flyfield service[/red]")
            return False
        except Exception as e:
            logger.debug(f"Flyfield service not available: {e}")
            if console:
                console.print(f"[yellow]Flyfield service error: {e}[/yellow]")
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
        if self.services_status.get("flyfield"):
            parts.append("Flyfield")
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
