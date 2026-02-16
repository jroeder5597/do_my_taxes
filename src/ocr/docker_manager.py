"""
Podman management for Tesseract OCR container.
Handles building, starting, and stopping the OCR service container.

Uses Podman instead of Docker for container management.
Podman is daemonless and rootless, making it more secure for desktop use.
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger

logger = get_logger(__name__)

# Container configuration
CONTAINER_NAME = "tesseract-ocr-service"
IMAGE_NAME = "tesseract-ocr-service"
DEFAULT_PORT = 5000
CONTAINER_PATH = Path(__file__).parent.parent.parent / "containers" / "tesseract-ocr"


class PodmanManager:
    """Manages the Tesseract OCR Podman container."""

    def __init__(self, port: int = DEFAULT_PORT):
        """
        Initialize Podman manager.

        Args:
            port: Port to expose the OCR service on
        """
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
        """Check if the OCR container is currently running."""
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
        """Check if the OCR image is built."""
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
        """
        Build the OCR Podman image.

        Returns:
            True if build succeeded, False otherwise
        """
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
                timeout=300,  # 5 minutes for build
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
        """
        Start the OCR container.

        Returns:
            True if container started successfully, False otherwise
        """
        # Check if already running
        if self.is_container_running():
            logger.info(f"Container {self.container_name} is already running")
            return True

        # Remove existing stopped container
        self.stop_container()

        logger.info(f"Starting container {self.container_name} on port {self.port}...")
        try:
            # Use 127.0.0.1 for port binding to work with Podman on Windows
            result = subprocess.run(
                ["podman", "run", "-d",
                 "-p", f"127.0.0.1:{self.port}:5000",
                 "--name", self.container_name,
                 self.image_name],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"Container started: {result.stdout.strip()}")
                # Wait for service to be ready
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
        """
        Stop the OCR container.

        Returns:
            True if container stopped successfully, False otherwise
        """
        try:
            # Check if container exists (running or stopped)
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

            # Stop the container
            subprocess.run(
                ["podman", "stop", self.container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Remove the container
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
        """
        Wait for the OCR service to be ready.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if service is ready, False otherwise
        """
        start_time = time.time()
        service_url = f"http://localhost:{self.port}"

        logger.info(f"Waiting for OCR service at {service_url}...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{service_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info("OCR service is ready")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)

        logger.error("OCR service did not become ready in time")
        return False

    def ensure_service_running(self, auto_build: bool = True) -> Optional[str]:
        """
        Ensure the OCR service is running, building and starting if necessary.

        Args:
            auto_build: Automatically build image if not present

        Returns:
            Service URL if running, None otherwise
        """
        # Check if Podman is available
        if not self.is_podman_available():
            logger.warning("Podman is not available")
            return None

        # Check if container is already running
        if self.is_container_running():
            logger.info(f"OCR container already running on port {self.port}")
            return f"http://localhost:{self.port}"

        # Check if image exists
        if not self.is_image_built():
            if auto_build:
                logger.info("OCR image not found, building...")
                if not self.build_image():
                    return None
            else:
                logger.warning("OCR image not built and auto_build=False")
                return None

        # Start the container
        if self.start_container():
            return f"http://localhost:{self.port}"

        return None

    def get_status(self) -> dict:
        """
        Get the current status of the OCR service.

        Returns:
            Dictionary with status information
        """
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


# Backward compatibility alias
DockerManager = PodmanManager


def ensure_ocr_service(port: int = DEFAULT_PORT, auto_build: bool = True) -> Optional[str]:
    """
    Convenience function to ensure OCR service is running.

    Args:
        port: Port for the OCR service
        auto_build: Automatically build image if needed

    Returns:
        Service URL if available, None otherwise
    """
    manager = PodmanManager(port=port)
    return manager.ensure_service_running(auto_build=auto_build)


def get_ocr_status(port: int = DEFAULT_PORT) -> dict:
    """
    Convenience function to get OCR service status.

    Args:
        port: Port for the OCR service

    Returns:
        Status dictionary
    """
    manager = PodmanManager(port=port)
    return manager.get_status()
