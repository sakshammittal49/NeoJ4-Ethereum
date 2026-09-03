"""
EnsHelpers — Ethereum Name Service Lookup

Equivalent of lib/ens_helpers.ex in the Elixir project.

ENS is like DNS for Ethereum — it maps human-readable names like
"vitalik.eth" to hex addresses like "0xd8da...".

This module queries The Graph's ENS subgraph to resolve ENS names
for transaction participants. Uses exponential backoff to handle
rate limiting (HTTP 429) from The Graph's public API.
"""

import logging

import httpx

from ethcule_poirot.helpers.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# The Graph's ENS subgraph endpoint
ENS_SUBGRAPH_URL = (
    "https://api.thegraph.com/subgraphs/name/ensdomains/ens"
)


async def _fetch_ens(client: httpx.AsyncClient, query: str) -> dict:
    """Send the ENS GraphQL query and return raw JSON data.

    Separated from check_for_ens so that retry_with_backoff can
    wrap just the HTTP call and retry on 429.

    Args:
        client: An httpx.AsyncClient instance.
        query: The GraphQL query string.

    Returns:
        The parsed JSON response dict.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses (including 429,
            which is caught by retry_with_backoff).
    """
    response = await client.post(
        ENS_SUBGRAPH_URL,
        json={"query": query},
    )
    response.raise_for_status()
    return response.json()


async def check_for_ens(to_address: str, from_address: str) -> dict[str, str]:
    """Look up ENS names for both the to and from addresses.

    Sends a GraphQL query to The Graph's ENS subgraph asking for domain
    names associated with both addresses. Retries with exponential backoff
    on HTTP 429 (rate limiting).

    Args:
        to_address: The recipient Ethereum address.
        from_address: The sender Ethereum address.

    Returns:
        A dict with keys "to_ens" and "from_ens", each containing the
        ENS name (e.g., "vitalik.eth") or an empty string if none exists.

    On API failure (after retries exhausted), returns empty strings for
    both (graceful degradation).
    """
    query = """
    {
        to_domains: domains(where: {resolvedAddress: "%s"}, first: 1) {
            name
        }
        from_domains: domains(where: {resolvedAddress: "%s"}, first: 1) {
            name
        }
    }
    """ % (to_address.lower(), from_address.lower())

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = await retry_with_backoff(
                _fetch_ens,
                client,
                query,
                max_retries=5,
                base_delay=1.0,
            )

        result_data = data.get("data", {})

        # Extract ENS name for the "to" address
        to_domains = result_data.get("to_domains", [])
        to_ens = to_domains[0]["name"] if to_domains else ""

        # Extract ENS name for the "from" address
        from_domains = result_data.get("from_domains", [])
        from_ens = from_domains[0]["name"] if from_domains else ""

        return {"to_ens": to_ens, "from_ens": from_ens}

    except Exception as e:
        # Graceful degradation: if ENS lookup fails after all retries
        logger.warning("ENS lookup failed for %s / %s: %s", to_address, from_address, e)
        return {"to_ens": "", "from_ens": ""}
