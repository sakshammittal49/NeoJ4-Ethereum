"""
EthculePoirot.AddressExplorer — The Worker / Individual Investigator

Equivalent of lib/ethcule_poirot/address_explorer.ex in the Elixir project.

Each AddressExplorer explores exactly ONE address and then terminates.
In Elixir this is a short-lived GenServer with restart: :transient.
In Python this is an async function that runs as an asyncio task.

Two scenarios based on depth:
    Depth = 0 (leaf node):
        - Checks if the address is a smart contract
        - Labels the node in Neo4j
        - Notifies the coordinator it's done
        - Exits

    Depth > 0 (explore transactions):
        - Fetches transactions via the API adapter
        - For each transaction: writes to Neo4j, gets counterparty, queues it
        - Notifies the coordinator it's done
        - Exits
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ethcule_poirot.neo4j_client.client import Neo4jClient
from ethcule_poirot.adapters.base import ApiAdapter

if TYPE_CHECKING:
    from ethcule_poirot.exploration.network_explorer import NetworkExplorer

logger = logging.getLogger(__name__)


class AddressExplorer:
    """Explores a single Ethereum address and self-terminates.

    This is the worker unit of the exploration engine. The NetworkExplorer
    coordinator spawns one AddressExplorer per address as an asyncio task.

    Attributes:
        eth_address: The address to explore.
        depth: How many more levels to recurse (0 = leaf node).
        api_adapter: The API adapter to use for fetching data.
        neo4j_client: The Neo4j client for writing to the database.
        coordinator: The NetworkExplorer that spawned this worker.
    """

    def __init__(
        self,
        eth_address: str,
        depth: int,
        api_adapter: ApiAdapter,
        neo4j_client: Neo4jClient,
        coordinator: NetworkExplorer,
    ) -> None:
        self.eth_address = eth_address
        self.depth = depth
        self.api_adapter = api_adapter
        self.neo4j_client = neo4j_client
        self.coordinator = coordinator

    async def run(self) -> None:
        """Execute the address exploration.

        This is the main entry point, called as an asyncio task.
        Mirrors the Elixir GenServer's init → handle_info flow.
        """
        try:
            if self.depth == 0:
                await self._explore_leaf()
            else:
                await self._explore_with_transactions()
        except Exception as e:
            # Graceful degradation: log the error, notify coordinator we're done,
            # and let the exploration continue without this address.
            logger.error(
                "Error exploring address %s at depth %d: %s",
                self.eth_address,
                self.depth,
                e,
            )
        finally:
            # Always notify the coordinator that this address is done,
            # whether we succeeded or failed. This prevents the exploration
            # from hanging if a single address fails.
            await self.coordinator.node_visited(self.eth_address)

    async def _explore_leaf(self) -> None:
        """Handle depth=0 exploration (leaf node — don't go deeper).

        1. Check if the address is a smart contract
        2. Set the appropriate label in Neo4j
        3. That's it — no transaction fetching.
        """
        logger.debug("Exploring leaf node: %s", self.eth_address)

        # Fetch address metadata (is it a contract?)
        address_info = await self.api_adapter.address_information(self.eth_address)

        # Set the appropriate label in Neo4j
        label = "SmartContract" if address_info.contract else "Account"
        await self.neo4j_client.set_node_label(self.eth_address, label)

        logger.debug("Leaf node %s labeled as %s", self.eth_address, label)

    async def _explore_with_transactions(self) -> None:
        """Handle depth>0 exploration (fetch and process transactions).

        1. Fetch transactions via the API adapter
        2. For each transaction: write to Neo4j, get counterparty, queue it
        3. If no transactions: just label the node and exit.
        """
        logger.info(
            "Exploring address %s at depth %d", self.eth_address, self.depth
        )

        # Fetch transactions from the API
        address_info = await self.api_adapter.transactions_for_address(
            self.eth_address
        )

        if not address_info.transactions:
            # Empty wallet — just set the node label and exit
            label = "SmartContract" if address_info.contract else "Account"
            await self.neo4j_client.set_node_label(self.eth_address, label)
            logger.info("Address %s has no transactions", self.eth_address)
            return

        # Process each transaction
        for trx in address_info.transactions:
            # Write the transaction to Neo4j and get the counterparty address
            # This is the synchronous (awaited) call — mirrors Elixir's GenServer.call
            next_address = await self.neo4j_client.transaction_relation(
                address_info, trx
            )

            # Queue the counterparty for exploration at depth - 1
            await self.coordinator.visit_node(next_address, self.depth - 1)

        logger.info(
            "Finished exploring %s — processed %d transactions",
            self.eth_address,
            len(address_info.transactions),
        )
