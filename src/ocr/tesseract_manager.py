"""
Podman manager for Tesseract OCR service.
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)

TESSERACT_SERVICE_URL = "http://localhost:5002"
CONTAINER_NAME = "tesseract-service"
IMAGE_NAME = "tesseract-service"


class TesseractPodmanManager:
    """Manages the Tesseract OCR service container."""
    
    def __init__(self, image_name: str = IMAGE_NAME, container_name: str = CONTAINER_NAME):
        self.image_name = image_name
        self.container_name = container_name
        self.port = 5002
    
    def is_image_built(self) -> bool:
        """Check if the Tesseract image is built."""
        try:
            result = subprocess.run(
                ["podman", "images", "-q", self.image_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return bool(result.stdout.strip())
        except Exception as e:
            logger.debug(f"Error checking for image: {e}")
            return False
    
    def build_image(self, force: bool = False) -> bool:
        """Build the Tesseract Docker image."""
        container_dir = Path(__file__).parent.parent / "containers" / "tesseract-service"
        
        if force:
            subprocess.run(
                ["podman", "rm", "-f", self.container_name],
                capture_output=True,
                timeout=30
            )
        
        try:
            result = subprocess.run(
                ["podman", "build", "-t", self.image_name, "."],
                cwd=container_dir,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to build image: {result.stderr}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error building image: {e}")
            return False
    
    def is_container_running(self) -> bool:
        """Check if the Tesseract container is running."""
        try:
            result = subprocess.run(
                ["podman", "ps", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return self.container_name in result.stdout
        except Exception as e:
            logger.debug(f"Error checking container status: {e}")
            return False
    
    def start_container(self) -> bool:
        """Start the Tesseract container."""
        if self.is_container_running():
            return True
        
        try:
            result = subprocess.run(
                [
                    "podman", "run", "-d",
                    "--name", self.container_name,
                    "-p", f"{self.port}:5002",
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to start container: {result.stderr}")
                return False
            
            # Wait for service to be ready
            for _ in range(10):
                time.sleep(1)
                if self.is_service_healthy():
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error starting container: {e}")
            return False
    
    def stop_container(self) -> bool:
        """Stop the Tesseract container."""
        try:
            result = subprocess.run(
                ["podman", "stop", self.container_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error stopping container: {e}")
            return False
    
    def remove_container(self) -> bool:
        """Remove the Tesseract container."""
        try:
            subprocess.run(
                ["podman", "rm", "-f", self.container_name],
                capture_output=True,
                timeout=30
            )
            return True
        except Exception as e:
            logger.error(f"Error removing container: {e}")
            return False
    
    def is_service_healthy(self) -> bool:
        """Check if the Tesseract service is healthy."""
        try:
            response = requests.get(f"{TESSERACT_SERVICE_URL}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


def ensure_tesseract_service(console=None) -> bool:
    """Ensure the Tesseract service is running."""
    try:
        manager = TesseractPodmanManager()
        
        if manager.is_container_running():
            if manager.is_service_healthy():
                if console:
                    console.print("[green]Tesseract service already running[/green]")
                return True
            else:
                manager.remove_container()
        
        if not manager.is_image_built():
            if console:
                console.print("[blue]Building Tesseract image...[/blue]")
            if not manager.build_image():
                if console:
                    console.print("[red]Failed to build Tesseract image[/red]")
                return False
        
        if console:
            console.print("[blue]Starting Tesseract service...[/blue]")
        
        if manager.start_container():
            if console:
                console.print("[green]Tesseract service started[/green]")
            return True
        
        if console:
            console.print("[red]Failed to start Tesseract service[/red]")
        return False
        
    except Exception as e:
        logger.debug(f"Tesseract service error: {e}")
        if console:
            console.print(f"[yellow]Tesseract service error: {e}[/yellow]")
        return False


def get_tesseract_status() -> dict:
    """Get the Tesseract service status."""
    manager = TesseractPodmanManager()
    return {
        "running": manager.is_container_running(),
        "healthy": manager.is_service_healthy() if manager.is_container_running() else False,
    }
