"""
Podman management for Qdrant vector database container.
Handles building, starting, and stopping the Qdrant service container.

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
CONTAINER_NAME = "qdrant-tax-service"
IMAGE_NAME = "qdrant/qdrant:latest"
DEFAULT_PORT = 6333


class QdrantManager:
    """Manages the Qdrant vector database Podman container."""

    def __init__(self, port: int = DEFAULT_PORT):
        """
        Initialize Qdrant manager.

        Args:
            port: Port to expose the Qdrant service on
        """
        self.port = port
        self.container_name = CONTAINER_NAME
        self.image_name = IMAGE_NAME
        self.data_dir = Path("db/qdrant_storage")

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
        """Check if the Qdrant container is currently running."""
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

    def is_image_available(self) -> bool:
        """Check if the Qdrant image is available locally."""
        try:
            result = subprocess.run(
                ["podman", "images", "--filter", f"reference={self.image_name}",
                 "--format", "{{.Repository}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return "qdrant" in result.stdout
        except Exception as e:
            logger.error(f"Error checking image: {e}")
            return False

    def pull_image(self) -> bool:
        """
        Pull the Qdrant image from Docker Hub.

        Returns:
            True if pull succeeded, False otherwise
        """
        logger.info(f"Pulling Qdrant image {self.image_name}...")
        try:
            result = subprocess.run(
                ["podman", "pull", self.image_name],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes for pull
            )
            if result.returncode == 0:
                logger.info(f"Successfully pulled image {self.image_name}")
                return True
            else:
                logger.error(f"Failed to pull image: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("Podman pull timed out")
            return False
        except Exception as e:
            logger.error(f"Error pulling image: {e}")
            return False

    def start_container(self) -> bool:
        """
        Start the Qdrant container.

        Returns:
            True if container started successfully, False otherwise
        """
        # Check if already running
        if self.is_container_running():
            logger.info(f"Container {self.container_name} is already running")
            return True

        # Remove existing stopped container
        self.stop_container()

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting container {self.container_name} on port {self.port}...")
        try:
            # Use 127.0.0.1 for port binding to work with Podman on Windows
            result = subprocess.run(
                ["podman", "run", "-d",
                 "-p", f"127.0.0.1:{self.port}:6333",
                 "--name", self.container_name,
                 "-v", f"{self.data_dir.absolute()}:/qdrant/storage",
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
        Stop the Qdrant container.

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
        Wait for the Qdrant service to be ready.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if service is ready, False otherwise
        """
        start_time = time.time()
        service_url = f"http://localhost:{self.port}"

        logger.info(f"Waiting for Qdrant service at {service_url}...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{service_url}/healthz", timeout=5)
                if response.status_code == 200:
                    logger.info("Qdrant service is ready")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)

        logger.error("Qdrant service did not become ready in time")
        return False

    def ensure_service_running(self, auto_pull: bool = True) -> Optional[str]:
        """
        Ensure the Qdrant service is running, pulling and starting if necessary.

        Args:
            auto_pull: Automatically pull image if not present

        Returns:
            Service URL if running, None otherwise
        """
        # Check if Podman is available
        if not self.is_podman_available():
            logger.warning("Podman is not available")
            return None

        # Check if container is already running
        if self.is_container_running():
            logger.info(f"Qdrant container already running on port {self.port}")
            return f"http://localhost:{self.port}"

        # Check if image exists
        if not self.is_image_available():
            if auto_pull:
                logger.info("Qdrant image not found, pulling...")
                if not self.pull_image():
                    return None
            else:
                logger.warning("Qdrant image not available and auto_pull=False")
                return None

        # Start the container
        if self.start_container():
            return f"http://localhost:{self.port}"

        return None

    def get_status(self) -> dict:
        """
        Get the current status of the Qdrant service.

        Returns:
            Dictionary with status information
        """
        status = {
            "podman_available": self.is_podman_available(),
            "image_available": False,
            "container_running": False,
            "service_url": None,
            "service_healthy": False,
        }

        if status["podman_available"]:
            status["image_available"] = self.is_image_available()
            status["container_running"] = self.is_container_running()

            if status["container_running"]:
                status["service_url"] = f"http://localhost:{self.port}"

                try:
                    response = requests.get(f"{status['service_url']}/healthz", timeout=5)
                    status["service_healthy"] = response.status_code == 200
                except requests.exceptions.RequestException:
                    pass

        return status


def ensure_qdrant_service(port: int = DEFAULT_PORT, auto_pull: bool = True) -> Optional[str]:
    """
    Convenience function to ensure Qdrant service is running.

    Args:
        port: Port for the Qdrant service
        auto_pull: Automatically pull image if needed

    Returns:
        Service URL if available, None otherwise
    """
    manager = QdrantManager(port=port)
    return manager.ensure_service_running(auto_pull=auto_pull)


def get_qdrant_status(port: int = DEFAULT_PORT) -> dict:
    """
    Convenience function to get Qdrant service status.

    Args:
        port: Port for the Qdrant service

    Returns:
        Status dictionary
    """
    manager = QdrantManager(port=port)
    return manager.get_status()
