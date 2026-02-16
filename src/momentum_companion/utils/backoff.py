from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def with_backoff(retries: int = 3, base_delay: float = 0.5, factor: float = 2.0) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to apply simple exponential backoff on exceptions.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = base_delay
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == retries - 1:
                        raise
                    time.sleep(delay)
                    delay *= factor

        return wrapper

    return decorator
