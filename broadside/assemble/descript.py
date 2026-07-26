"""Descript API client for cloud-based video assembly.

Uses Descript's API for import, Underlord agent processing,
and publishing. All authentication via Bearer token from
DESCRIPT_API_TOKEN environment variable.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.descriptapi.com"
_POLL_INITIAL_INTERVAL = 2.0
_POLL_BACKOFF_FACTOR = 1.5
_POLL_MAX_INTERVAL = 30.0


class DescriptError(Exception):
    """Raised when a Descript API call fails."""


def _get_token() -> str:
    """Retrieve Descript API token from environment."""
    token = os.environ.get("DESCRIPT_API_TOKEN", "")
    if not token:
        raise DescriptError(
            "DESCRIPT_API_TOKEN environment variable is not set. "
            "Set it to your Descript API Bearer token."
        )
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def poll_job(token: str, job_id: str, *, max_wait: int = 300) -> dict:
    """Poll a Descript job until completion or timeout.

    Uses exponential backoff starting at 2s, capped at 30s intervals.

    Args:
        token: Descript API Bearer token.
        job_id: The job ID to poll.
        max_wait: Maximum seconds to wait before raising timeout error.

    Returns:
        The completed job response dict.

    Raises:
        DescriptError: If job fails or times out.
    """
    url = f"{BASE_URL}/v1/jobs/{job_id}"
    headers = _headers(token)
    interval = _POLL_INITIAL_INTERVAL
    elapsed = 0.0

    while elapsed < max_wait:
        resp = httpx.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise DescriptError(
                f"Poll job {job_id} returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        status = data.get("status", "")

        if status == "done":
            logger.info("Job %s completed", job_id)
            return data
        if status in ("failed", "error"):
            error_msg = data.get("error", data.get("message", "Unknown error"))
            raise DescriptError(f"Job {job_id} failed: {error_msg}")

        logger.debug("Job %s status: %s, waiting %.1fs", job_id, status, interval)
        time.sleep(interval)
        elapsed += interval
        interval = min(interval * _POLL_BACKOFF_FACTOR, _POLL_MAX_INTERVAL)

    raise DescriptError(f"Job {job_id} timed out after {max_wait}s")


def import_media(token: str, file_paths: list[str]) -> str:
    """Import media files into a Descript project.

    Args:
        token: Descript API Bearer token.
        file_paths: List of local file paths to import.

    Returns:
        The created project ID.

    Raises:
        DescriptError: If import fails.
    """
    url = f"{BASE_URL}/v1/jobs/import/project_media"
    headers = _headers(token)
    payload = {"file_paths": file_paths}

    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code not in (200, 201, 202):
        raise DescriptError(
            f"Import media returned {resp.status_code}: {resp.text}"
        )

    data = resp.json()
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise DescriptError(f"No job_id in import response: {data}")

    result = poll_job(token, job_id)
    project_id = (
        result.get("project_id")
        or result.get("result", {}).get("project_id", "")
    )
    if not project_id:
        raise DescriptError(f"No project_id in completed job: {result}")

    logger.info("Imported %d files into project %s", len(file_paths), project_id)
    return project_id


def run_agent(
    token: str,
    project_id: str,
    prompt: str,
    model: str | None = None,
) -> str:
    """Run a Descript Underlord agent action on a project.

    Args:
        token: Descript API Bearer token.
        project_id: Target project ID.
        prompt: Underlord prompt describing the action.
        model: Optional agent model name.

    Returns:
        The completed job ID.

    Raises:
        DescriptError: If agent run fails.
    """
    url = f"{BASE_URL}/v1/jobs/agent"
    headers = _headers(token)
    payload: dict = {
        "project_id": project_id,
        "prompt": prompt,
    }
    if model:
        payload["model"] = model

    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code not in (200, 201, 202):
        raise DescriptError(
            f"Agent run returned {resp.status_code}: {resp.text}"
        )

    data = resp.json()
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise DescriptError(f"No job_id in agent response: {data}")

    result = poll_job(token, job_id, max_wait=600)
    logger.info("Agent completed on project %s (job %s)", project_id, job_id)
    return job_id


def publish_project(token: str, project_id: str) -> str:
    """Publish a Descript project and return the download URL.

    Args:
        token: Descript API Bearer token.
        project_id: The project to publish.

    Returns:
        Download URL for the published video.

    Raises:
        DescriptError: If publish fails.
    """
    url = f"{BASE_URL}/v1/jobs/publish"
    headers = _headers(token)
    payload = {"project_id": project_id}

    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code not in (200, 201, 202):
        raise DescriptError(
            f"Publish returned {resp.status_code}: {resp.text}"
        )

    data = resp.json()
    job_id = data.get("job_id") or data.get("id")
    if not job_id:
        raise DescriptError(f"No job_id in publish response: {data}")

    result = poll_job(token, job_id, max_wait=600)
    download_url = (
        result.get("download_url")
        or result.get("result", {}).get("download_url", "")
        or result.get("url", "")
    )
    if not download_url:
        raise DescriptError(f"No download URL in publish result: {result}")

    logger.info("Project %s published: %s", project_id, download_url)
    return download_url


def list_models(token: str) -> list[str]:
    """List available Descript agent models.

    Args:
        token: Descript API Bearer token.

    Returns:
        List of model name strings.

    Raises:
        DescriptError: If request fails.
    """
    url = f"{BASE_URL}/v1/agent/models"
    headers = _headers(token)

    resp = httpx.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise DescriptError(
            f"List models returned {resp.status_code}: {resp.text}"
        )

    data = resp.json()
    models = data if isinstance(data, list) else data.get("models", [])
    return [m if isinstance(m, str) else m.get("name", str(m)) for m in models]
