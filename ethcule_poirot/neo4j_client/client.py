"""
Neo4j.Client — The Database Gatekeeper

Equivalent of lib/neo4j/client.ex in the Elixir project.

This is the central database writer. In Elixir it's a GenServer that holds the
Neo4j connection in its state and responds to messages. In Python, it's an async
class that holds an async Neo4j driver and exposes awaitable methods.

Operations:
    clear_database()                          — Delete all nodes and relationships
    create_indexes()                          — Create indexes for fast lookups
    set_node_label(address, label)            — Add a label to a node
    highlight_accounts_of_interest(addresses) — Tag nodes with "Interest" label
    transaction_relation(address_info, trx)   — Create/update nodes + relationship,
                                                returns the counterparty address
"""

import logging

from neo4j import AsyncGraphDatabase, AsyncDriver

from ethcule_poirot import config
from ethcule_poirot.models.address import Address
from ethcule_poirot.models.transaction import Transaction
from ethcule_poirot.neo4j_client.cypher import prepared_statement
from ethcule_poirot.helpers.ens import check_for_ens

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Async Neo4j database client.

    Manages the driver lifecycle and provides all database operations
    needed by the exploration engine.
    """

    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Initialize the Neo4j async driver (equivalent of Bolt.Sips starting)."""
        self._driver = AsyncGraphDatabase.driver(
            config.DATABASE_URL,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        logger.info("Connected to Neo4j at %s", config.DATABASE_URL)

    async def close(self) -> None:
        """Close the Neo4j driver and release all connections."""
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j connection closed")

    async def _execute(self, query: str) -> list[dict]:
        """Execute a Cypher query and return the results as a list of dicts.

        Args:
            query: A fully-formed Cypher query string (no placeholders).

        Returns:
            A list of record dicts from the query result.
        """
        if not self._driver:
            raise RuntimeError("Neo4jClient is not connected. Call connect() first.")

        async with self._driver.session() as session:
            result = await session.run(query)
            records = await result.data()
            return records

    # ------------------------------------------------------------------
    # Fire-and-forget operations (async send in Elixir)
    # ------------------------------------------------------------------

    async def clear_database(self) -> None:
        """Delete ALL nodes and relationships from Neo4j — a full reset.

        Equivalent of the Elixir :clear_database message handler.
        """
        await self._execute("MATCH (n) DETACH DELETE n")
        logger.info("Database cleared — all nodes and relationships deleted")

    async def create_indexes(self) -> None:
        """Create database indexes for fast lookups.

        Creates indexes on:
            - Account.eth_address
            - SmartContract.eth_address
            - TO.hash (relationship property index)

        Equivalent of the Elixir :create_indexes message handler.
        """
        index_queries = [
            "CREATE INDEX IF NOT EXISTS FOR (a:Account) ON (a.eth_address)",
            "CREATE INDEX IF NOT EXISTS FOR (s:SmartContract) ON (s.eth_address)",
            "CREATE INDEX IF NOT EXISTS FOR ()-[r:TO]-() ON (r.hash)",
        ]
        for query in index_queries:
            await self._execute(query)
        logger.info("Database indexes created")

    async def set_node_label(self, address: str, label: str) -> None:
        """Find a node by its eth_address and add a label.

        Args:
            address: The Ethereum address of the node.
            label: The label to add (e.g., "Account", "SmartContract", "Initial").

        Equivalent of the Elixir {:set_node_label, address, label} message handler.
        """
        query = prepared_statement(
            "MATCH (n {eth_address: '{{address}}'}) SET n:{{label}}",
            {"address": address, "label": label},
        )
        await self._execute(query)
        logger.debug("Set label '%s' on node %s", label, address)

    async def highlight_accounts_of_interest(self, addresses: list[str]) -> None:
        """Tag a list of addresses with an 'Interest' label for visualization.

        Args:
            addresses: List of Ethereum addresses to highlight.

        Equivalent of the Elixir {:highlight, addresses} message handler.
        """
        for address in addresses:
            await self.set_node_label(address, "Interest")
        logger.info("Highlighted %d accounts of interest", len(addresses))

    # ------------------------------------------------------------------
    # Synchronous operation (GenServer.call in Elixir)
    # ------------------------------------------------------------------

    async def transaction_relation(
        self, address_info: Address, transaction: Transaction
    ) -> str:
        """Create/update nodes and a :TO relationship representing a transaction.

        This is the MOST IMPORTANT function. It:
        1. Determines the counterparty (the "other" address in the transaction)
        2. Looks up ENS names for both addresses
        3. Builds and executes a MERGE Cypher query
        4. Returns the counterparty address for the crawler to explore next

        Args:
            address_info: The Address struct being explored.
            transaction: The Transaction struct to write.

        Returns:
            The counterparty address string (the address on the other side
            of the transaction).

        Equivalent of the Elixir {:transaction_relation, ...} call handler.
        This is the only "synchronous" operation — in Python, the caller
        simply awaits the coroutine.
        """
        current_address = address_info.eth_address

        # Determine counterparty: if to_address is us, counterparty is from, and vice versa
        if transaction.to_address.lower() == current_address.lower():
            counterparty = transaction.from_address
        else:
            counterparty = transaction.to_address

        # Look up ENS names for both addresses
        ens_info = await check_for_ens(
            transaction.to_address, transaction.from_address
        )

        # Determine node label based on whether the current address is a contract
        node_label = "SmartContract" if address_info.contract else "Account"

        # Build the MERGE Cypher query
        # This creates nodes if they don't exist and creates the :TO relationship
        query = prepared_statement(
            """
            MERGE (current {eth_address: '{{current_address}}'})
            SET current:{{node_label}}
            MERGE (to_node {eth_address: '{{to_address}}'})
            SET to_node.ens_name = '{{to_ens}}'
            MERGE (from_node {eth_address: '{{from_address}}'})
            SET from_node.ens_name = '{{from_ens}}'
            MERGE (from_node)-[r:TO {hash: '{{tx_hash}}'}]->(to_node)
            SET r.eth_value = '{{value}}', r.status = '{{status}}'
            """,
            {
                "current_address": current_address,
                "node_label": node_label,
                "to_address": transaction.to_address,
                "to_ens": ens_info["to_ens"],
                "from_address": transaction.from_address,
                "from_ens": ens_info["from_ens"],
                "tx_hash": transaction.hash,
                "value": transaction.value,
                "status": transaction.status,
            },
        )

        await self._execute(query)
        logger.debug(
            "Created transaction relation: %s -> %s (hash: %s)",
            transaction.from_address,
            transaction.to_address,
            transaction.hash,
        )

        return counterparty
