from __future__ import annotations

import logging
from typing import Optional


def setup_logging(log_path: Optional[str] = None, level: int = logging.INFO) -> None:
    """Configure application logging per specs.md §14."""
    handlers = None
    if log_path:
        handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()]
    logging.basicConfig(level=level, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("websocket").setLevel(logging.WARNING)
