from __future__ import annotations

import os

import uvicorn

from momentum_companion.web.app import create_app


if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.getenv("TOS_COMPANION_HOST", "127.0.0.1"),
        port=int(os.getenv("TOS_COMPANION_PORT", "8787")),
        log_level=os.getenv("TOS_COMPANION_LOG_LEVEL", "info"),
    )
