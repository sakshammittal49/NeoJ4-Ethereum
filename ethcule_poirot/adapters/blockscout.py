"""
Adapters.Api.Blockscout — Ethereum Mainnet Transaction Adapter

Equivalent of lib/adapters/api/blockscout.ex in the Elixir project.

Uses the Blockscout GraphQL API to fetch real Ethereum blockchain transactions.
This is the default/primary adapter for the application.

Key behaviors:
    - Fetches the last 23 transactions per address (Blockscout complexity limit)
    - Converts values from Wei to ETH (dividing by 10^18)
    - Determines if an address is a smart contract via contractCode
    - Graceful degradation: on API failure, returns empty transactions
"""

import logging
from decimal import Decimal

import httpx

from ethcule_poirot import config
from ethcule_poirot.adapters.base import ApiAdapter
from ethcule_poirot.models.address import Address
from ethcule_poirot.models.transaction import Transaction
from ethcule_poirot.helpers.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Wei to ETH conversion factor
WEI_TO_ETH = Decimal("1000000000000000000")  # 10^18


class BlockscoutAdapter(ApiAdapter):
    """Blockscout GraphQL API adapter for Ethereum mainnet transactions."""

    def __init__(self) -> None:
        self._api_url: str = ""
        self._timeout: float = 120.0
        self._client: httpx.AsyncClient | None = None

    async def initial_setup(self) -> None:
        """Configure the HTTP client with the Blockscout API URL and timeout.

        Reads settings from the config module (which loads from env vars).
        Equivalent of the Elixir initial_setup/0 that configures Neuron.
        """
        self._api_url = config.BLOCKSCOUT_API_URL
        self._timeout = config.API_TIMEOUT
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info(
            "Blockscout adapter initialized: url=%s, timeout=%.0fs",
            self._api_url,
            self._timeout,
        )

    async def _raw_post(self, graphql_query: str) -> dict:
        """Send a raw HTTP POST to Blockscout and return parsed JSON.

        Separated from _query so that retry_with_backoff can wrap
        just the HTTP call and retry on 429.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses (429 is caught
                by the retry wrapper).
        """
        response = await self._client.post(
            self._api_url,
            json={"query": graphql_query},
        )
        response.raise_for_status()
        return response.json()

    async def _query(self, graphql_query: str) -> dict | None:
        """Send a GraphQL query to Blockscout and return the parsed response.

        Retries with exponential backoff on HTTP 429 (rate limiting).

        Args:
            graphql_query: The GraphQL query string.

        Returns:
            The parsed JSON response dict, or None on failure.
        """
        if not self._client:
            raise RuntimeError("BlockscoutAdapter not initialized. Call initial_setup() first.")

        try:
            data = await retry_with_backoff(
                self._raw_post,
                graphql_query,
                max_retries=5,
                base_delay=1.0,
            )

            if "errors" in data:
                logger.warning("Blockscout GraphQL errors: %s", data["errors"])
                return None

            return data.get("data")

        except Exception as e:
            logger.warning("Blockscout API call failed: %s", e)
            return None

    async def transactions_for_address(self, address: str) -> Address:
        """Fetch the last 23 transactions for an Ethereum address.

        Sends a GraphQL query requesting transactions and contractCode.
        Converts Wei values to ETH. Returns an Address struct.

        23 is the maximum allowed by Blockscout's query complexity limits.

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address with eth_address, contract flag, and transactions list.
            On failure, returns an Address with empty transactions.
        """
        query = """
        {
            address(hash: "%s") {
                contractCode
                transactions(first: 10) {
                    edges {
                        node {
                            hash
                            toAddressHash
                            fromAddressHash
                            value
                            status
                        }
                    }
                }
            }
        }
        """ % address

        data = await self._query(query)

        if not data or not data.get("address"):
            logger.warning(
                "No data returned for address %s — returning empty transactions",
                address,
            )
            return Address(eth_address=address, contract=False, transactions=[])

        address_data = data["address"]

        # Determine if this is a smart contract
        is_contract = address_data.get("contractCode") is not None

        # Parse transactions
        transactions: list[Transaction] = []
        edges = (
            address_data.get("transactions", {}).get("edges", [])
            if address_data.get("transactions")
            else []
        )

        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue

            # Convert Wei to ETH
            raw_value = node.get("value", "0")
            try:
                eth_value = str(Decimal(raw_value) / WEI_TO_ETH)
            except Exception:
                eth_value = "0"

            tx = Transaction(
                hash=node.get("hash", ""),
                to_address=node.get("toAddressHash", ""),
                from_address=node.get("fromAddressHash", ""),
                value=eth_value,
                status=node.get("status", "UNRESOLVED"),
            )
            transactions.append(tx)

        logger.info(
            "Fetched %d transactions for %s (contract=%s)",
            len(transactions),
            address,
            is_contract,
        )

        return Address(
            eth_address=address,
            contract=is_contract,
            transactions=transactions,
        )

    async def address_information(self, address: str) -> Address:
        """Fetch metadata about an address (is it a smart contract?).

        Queries only the contractCode field to determine contract status.

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address with eth_address and contract flag populated.
        """
        query = """
        {
            address(hash: "%s") {
                contractCode
            }
        }
        """ % address

        data = await self._query(query)

        if not data or not data.get("address"):
            return Address(eth_address=address, contract=False)

        is_contract = data["address"].get("contractCode") is not None
        return Address(eth_address=address, contract=is_contract)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
