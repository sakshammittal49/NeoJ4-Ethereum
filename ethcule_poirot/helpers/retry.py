"""
Retry — Exponential Backoff Utility for HTTP Requests

Provides a reusable async retry wrapper that catches HTTP 429 (Too Many Requests)
responses and retries with exponential backoff + jitter, instead of dropping
the request entirely.

Used by the ENS helper and API adapters to gracefully handle rate limiting
from external services like The Graph and Blockscout.
"""

import asyncio
import logging
import random
from typing import TypeVar, Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default retry configuration
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY = 1.0    # seconds
DEFAULT_MAX_DELAY = 30.0    # seconds
DEFAULT_JITTER = 0.5        # ±50% randomization


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float = DEFAULT_JITTER,
    **kwargs,
) -> T:
    """Execute an async function with exponential backoff on HTTP 429 errors.

    On a 429 response, waits with exponential backoff (1s, 2s, 4s, 8s, ...)
    plus random jitter before retrying. Non-429 errors are raised immediately.

    Args:
        func: The async function to call.
        *args: Positional arguments to pass to func.
        max_retries: Maximum number of retry attempts (default: 5).
        base_delay: Initial delay in seconds (default: 1.0).
        max_delay: Maximum delay cap in seconds (default: 30.0).
        jitter: Random jitter factor, e.g. 0.5 means ±50% (default: 0.5).
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The return value of func.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429:
                # Non-429 error — don't retry, raise immediately
                raise

            last_exception = e

            if attempt == max_retries:
                # Exhausted all retries
                logger.warning(
                    "Rate limited (429) after %d retries — giving up: %s",
                    max_retries,
                    e,
                )
                raise

            # Calculate delay with exponential backoff + jitter
            delay = min(base_delay * (2 ** attempt), max_delay)
            jittered_delay = delay * (1 + random.uniform(-jitter, jitter))

            logger.info(
                "Rate limited (429) on attempt %d/%d — retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                jittered_delay,
            )
            await asyncio.sleep(jittered_delay)

    # Should never reach here, but just in case
    raise last_exception  # type: ignore[misc]
