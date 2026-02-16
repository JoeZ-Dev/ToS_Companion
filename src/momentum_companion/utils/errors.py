from __future__ import annotations

from typing import Any


def map_http_error(exc: Exception) -> str:
    """Map HTTP exceptions to error taxonomy labels."""
    # Placeholder; would inspect httpx.HTTPStatusError etc.
    return "DATA_INTEGRITY_ERROR"
