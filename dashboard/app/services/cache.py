"""
Decorator de caché en memoria con TTL (mismo patrón que @st.cache_data
del proyecto de referencia, pero explícito y testeable fuera de Streamlit).
"""

import time
import functools
from typing import Any, Callable


def cached(ttl_seconds: int = 300) -> Callable:
    """
    Decorator que cachea el resultado de una función en memoria por
    `ttl_seconds`. La función decorada no sabe que está siendo
    cacheada (patrón Decorator, transparencia total).
    """

    def decorator(func: Callable) -> Callable:
        store: dict[tuple, tuple[float, Any]] = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()

            if key in store:
                timestamp, value = store[key]
                if now - timestamp < ttl_seconds:
                    return value

            value = func(*args, **kwargs)
            store[key] = (now, value)
            return value

        wrapper.clear_cache = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator
