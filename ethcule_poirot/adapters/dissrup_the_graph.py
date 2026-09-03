"""
Adapters.Api.DissrupTheGraph — NFT Marketplace Adapter

Equivalent of lib/adapters/api/dissrup_the_graph.ex in the Elixir project.

Uses The Graph's subgraph API to fetch NFT sale data from the Dissrup
marketplace. This is a proof-of-concept showing the system works with
more than just basic Ethereum transactions.

Key behaviors:
    - Queries both sales (where address sold an NFT) and buys (where address bought)
    - Maps sales/buys to Transaction structs
    - All statuses are hardcoded to "OK" (subgraph data is already confirmed)
"""

import logging

import httpx

from ethcule_poirot.adapters.base import ApiAdapter
from ethcule_poirot.models.address import Address
from ethcule_poirot.models.transaction import Transaction

logger = logging.getLogger(__name__)

# The Graph subgraph URL for Dissrup NFT marketplace
DISSRUP_SUBGRAPH_URL = (
    "https://api.thegraph.com/subgraphs/name/dissrup/dissrup-marketplace"
)


class DissrupTheGraphAdapter(ApiAdapter):
    """The Graph subgraph adapter for Dissrup NFT marketplace transactions."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def initial_setup(self) -> None:
        """Initialize the HTTP client for The Graph API."""
        self._client = httpx.AsyncClient(timeout=60.0)
        logger.info("DissrupTheGraph adapter initialized")

    async def _query(self, graphql_query: str) -> dict | None:
        """Send a GraphQL query to The Graph and return the parsed response.

        Args:
            graphql_query: The GraphQL query string.

        Returns:
            The parsed JSON response dict, or None on failure.
        """
        if not self._client:
            raise RuntimeError(
                "DissrupTheGraphAdapter not initialized. Call initial_setup() first."
            )

        try:
            response = await self._client.post(
                DISSRUP_SUBGRAPH_URL,
                json={"query": graphql_query},
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.warning("TheGraph GraphQL errors: %s", data["errors"])
                return None

            return data.get("data")

        except Exception as e:
            logger.warning("TheGraph API call failed: %s", e)
            return None

    async def transactions_for_address(self, address: str) -> Address:
        """Fetch NFT sale/buy transactions for an address from Dissrup.

        Queries both:
        - Sales: where the address sold an NFT (from_address = this address)
        - Buys: where the address bought an NFT (to_address = this address)

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address with combined sale and buy transactions.
        """
        query = """
        {
            sales: nftSales(where: {seller: "%s"}) {
                id
                buyer
                seller
                price
            }
            buys: nftSales(where: {buyer: "%s"}) {
                id
                buyer
                seller
                price
            }
        }
        """ % (address.lower(), address.lower())

        data = await self._query(query)

        if not data:
            logger.warning(
                "No data returned for address %s — returning empty transactions",
                address,
            )
            return Address(eth_address=address, contract=False, transactions=[])

        transactions: list[Transaction] = []

        # Process sales: this address is the seller (from_address)
        for sale in data.get("sales", []):
            tx = Transaction(
                hash=sale.get("id", ""),
                from_address=address,
                to_address=sale.get("buyer", ""),
                value=sale.get("price", "0"),
                status="OK",  # Subgraph data is already confirmed
            )
            transactions.append(tx)

        # Process buys: this address is the buyer (to_address)
        for buy in data.get("buys", []):
            tx = Transaction(
                hash=buy.get("id", ""),
                from_address=buy.get("seller", ""),
                to_address=address,
                value=buy.get("price", "0"),
                status="OK",  # Subgraph data is already confirmed
            )
            transactions.append(tx)

        logger.info(
            "Fetched %d transactions for %s from Dissrup (sales=%d, buys=%d)",
            len(transactions),
            address,
            len(data.get("sales", [])),
            len(data.get("buys", [])),
        )

        return Address(
            eth_address=address,
            contract=False,
            transactions=transactions,
        )

    async def address_information(self, address: str) -> Address:
        """Fetch metadata about an address.

        The Dissrup subgraph doesn't provide contract information,
        so all addresses are assumed to be regular accounts.

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address with contract=False.
        """
        return Address(eth_address=address, contract=False)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
