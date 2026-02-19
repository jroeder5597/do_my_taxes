"""
Podman management for PDFPlumber Tax extraction container.
Handles building, starting, and stopping the pdfplumber-tax-service container.
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)

CONTAINER_NAME = "pdfplumber-tax-service"
IMAGE_NAME = "pdfplumber-tax-service"
DEFAULT_PORT = 5001
CONTAINER_PATH = Path(__file__).parent.parent.parent / "containers" / "pdfplumber-tax-service"


class PDFPlumberTaxPodmanManager:
    """Manages the PDFPlumber Tax extraction Podman container."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.container_name = CONTAINER_NAME
        self.image_name = IMAGE_NAME
        self.container_path = CONTAINER_PATH

    def is_podman_available(self) -> bool:
        """Check if Podman is available on the system."""
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.debug(f"Podman available: {result.stdout.strip()}")
                return True
        except FileNotFoundError:
            logger.warning("Podman command not found")
        except subprocess.TimeoutExpired:
            logger.warning("Podman command timed out")
        except Exception as e:
            logger.warning(f"Error checking Podman: {e}")
        return False

    def is_container_running(self) -> bool:
        """Check if the Flyfield container is currently running."""
        try:
            result = subprocess.run(
                ["podman", "ps", "--filter", f"name={self.container_name}",
                 "--filter", "status=running", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return self.container_name in result.stdout
        except Exception as e:
            logger.error(f"Error checking container status: {e}")
            return False

    def is_image_built(self) -> bool:
        """Check if the Flyfield image is built."""
        try:
            result = subprocess.run(
                ["podman", "images", "--filter", f"reference={self.image_name}",
                 "--format", "{{.Repository}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return self.image_name in result.stdout
        except Exception as e:
            logger.error(f"Error checking image: {e}")
            return False

    def build_image(self) -> bool:
        """Build the Flyfield Podman image."""
        if not self.container_path.exists():
            logger.error(f"Container path not found: {self.container_path}")
            return False

        logger.info(f"Building Podman image {self.image_name}...")
        try:
            result = subprocess.run(
                ["podman", "build", "-t", self.image_name, "."],
                cwd=str(self.container_path),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                logger.info(f"Successfully built image {self.image_name}")
                return True
            else:
                logger.error(f"Failed to build image: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("Podman build timed out")
            return False
        except Exception as e:
            logger.error(f"Error building image: {e}")
            return False

    def start_container(self) -> bool:
        """Start the Flyfield container."""
        if self.is_container_running():
            logger.info(f"Container {self.container_name} is already running")
            return True

        self.stop_container()

        logger.info(f"Starting container {self.container_name} on port {self.port}...")
        try:
            result = subprocess.run(
                ["podman", "run", "-d",
                 "-p", f"127.0.0.1:{self.port}:5001",
                 "--name", self.container_name,
                 self.image_name],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"Container started: {result.stdout.strip()}")
                return self._wait_for_service()
            else:
                logger.error(f"Failed to start container: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("Podman run timed out")
            return False
        except Exception as e:
            logger.error(f"Error starting container: {e}")
            return False

    def stop_container(self) -> bool:
        """Stop the Flyfield container."""
        try:
            result = subprocess.run(
                ["podman", "ps", "-a", "--filter", f"name={self.container_name}",
                 "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if self.container_name not in result.stdout:
                logger.debug(f"Container {self.container_name} does not exist")
                return True

            subprocess.run(
                ["podman", "stop", self.container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            subprocess.run(
                ["podman", "rm", self.container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            logger.info(f"Container {self.container_name} stopped and removed")
            return True
        except Exception as e:
            logger.error(f"Error stopping container: {e}")
            return False

    def _wait_for_service(self, timeout: int = 30) -> bool:
        """Wait for the Flyfield service to be ready."""
        start_time = time.time()
        service_url = f"http://localhost:{self.port}"

        logger.info(f"Waiting for Flyfield service at {service_url}...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{service_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info("Flyfield service is ready")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)

        logger.error("Flyfield service did not become ready in time")
        return False

    def ensure_service_running(self, auto_build: bool = True) -> Optional[str]:
        """Ensure the Flyfield service is running."""
        if not self.is_podman_available():
            logger.warning("Podman is not available")
            return None

        if self.is_container_running():
            logger.info(f"Flyfield container already running on port {self.port}")
            return f"http://localhost:{self.port}"

        if not self.is_image_built():
            if auto_build:
                logger.info("Flyfield image not found, building...")
                if not self.build_image():
                    return None
            else:
                logger.warning("Flyfield image not built and auto_build=False")
                return None

        if self.start_container():
            return f"http://localhost:{self.port}"

        return None

    def get_status(self) -> dict:
        """Get the current status of the Flyfield service."""
        status = {
            "podman_available": self.is_podman_available(),
            "image_built": False,
            "container_running": False,
            "service_url": None,
            "service_healthy": False,
        }

        if status["podman_available"]:
            status["image_built"] = self.is_image_built()
            status["container_running"] = self.is_container_running()

            if status["container_running"]:
                status["service_url"] = f"http://localhost:{self.port}"

                try:
                    response = requests.get(f"{status['service_url']}/health", timeout=5)
                    status["service_healthy"] = response.status_code == 200
                except requests.exceptions.RequestException:
                    pass

        return status


def ensure_pdfplumber_tax_service(port: int = DEFAULT_PORT, auto_build: bool = True) -> Optional[str]:
    """Convenience function to ensure PDFPlumber Tax service is running."""
    manager = PDFPlumberTaxPodmanManager(port=port)
    return manager.ensure_service_running(auto_build=auto_build)


def get_pdfplumber_tax_status(port: int = DEFAULT_PORT) -> dict:
    """Convenience function to get PDFPlumber Tax service status."""
    manager = PDFPlumberTaxPodmanManager(port=port)
    return manager.get_status()
