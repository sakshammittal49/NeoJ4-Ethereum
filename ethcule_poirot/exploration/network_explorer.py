"""
EthculePoirot.NetworkExplorer — The Brain / Coordinator

Equivalent of lib/ethcule_poirot/network_explorer.ex in the Elixir project.

This is the CENTRAL COORDINATOR of the entire exploration. In Elixir it's a
GenServer that tracks state and manages AddressExplorer processes. In Python
it's an async class that uses asyncio tasks and a semaphore for pool control.

Responsibilities:
    - Track which addresses have been explored (to avoid re-exploring)
    - Track which addresses are currently being explored
    - Maintain a queue of addresses waiting to be explored
    - Enforce a pool size limit (default: 30 concurrent explorers)
    - Detect completion (when both exploring and remaining are empty)

State:
    eth_address     — The initial address that started the exploration
    depth           — How deep to explore
    known           — set() of ALL addresses ever seen (explored or queued)
    exploring       — set() of addresses currently being explored
    remaining       — deque() of (address, depth) tuples waiting for a slot
    api_adapter     — Which API adapter to use
    processes_count — How many explorer tasks are running right now
    pool_size       — Max concurrent explorer tasks
"""

import asyncio
import logging
from collections import deque

from ethcule_poirot import config
from ethcule_poirot.adapters.base import ApiAdapter
from ethcule_poirot.neo4j_client.client import Neo4jClient
from ethcule_poirot.exploration.address_explorer import AddressExplorer

logger = logging.getLogger(__name__)


class NetworkExplorer:
    """Central coordinator for the blockchain exploration.

    Manages the BFS traversal of the Ethereum address graph, spawning
    AddressExplorer tasks and enforcing concurrency limits.

    This is the Python equivalent of the Elixir GenServer that processes
    :start, :add_to_queue, and :remove_from_queue messages.
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        api_adapter: ApiAdapter,
        pool_size: int | None = None,
    ) -> None:
        """Initialize the NetworkExplorer.

        Args:
            neo4j_client: The Neo4j client for database operations.
            api_adapter: The API adapter for fetching blockchain data.
            pool_size: Max concurrent explorer tasks. Defaults to config.POOL_SIZE.
        """
        self.neo4j_client = neo4j_client
        self.api_adapter = api_adapter
        self.pool_size = pool_size or config.POOL_SIZE

        # Exploration state — reset on each explore() call
        self.eth_address: str = ""
        self.depth: int = 0
        self.known: set[str] = set()
        self.exploring: set[str] = set()
        self.remaining: deque[tuple[str, int]] = deque()
        self.processes_count: int = 0

        # asyncio primitives for coordination
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()
        self._completion_event = asyncio.Event()

    async def explore(self, address: str, depth: int) -> None:
        """Start exploring from an initial address.

        This is the main entry point — equivalent of the Elixir
        {:start, address, depth, api_adapter} message handler.

        Resets all state, performs initial setup, and kicks off the BFS.
        Blocks until the entire exploration is complete.

        Args:
            address: The Ethereum address to start from.
            depth: How many levels deep to explore.
        """
        # Normalize address to lowercase (Ethereum addresses are case-insensitive)
        address = address.lower()

        logger.info("=" * 60)
        logger.info("Starting exploration of %s at depth %d", address, depth)
        logger.info("Pool size: %d concurrent explorers", self.pool_size)
        logger.info("=" * 60)

        # Reset state completely (mirrors the Elixir :start handler)
        self.eth_address = address
        self.depth = depth
        self.known = set()
        self.exploring = set()
        self.remaining = deque()
        self.processes_count = 0
        self._tasks = set()
        self._completion_event.clear()

        # Perform initial API adapter setup
        await self.api_adapter.initial_setup()

        # Kick off the exploration by adding the initial address to the queue
        # (mirrors: send(self(), {:add_to_queue, address, depth}))
        await self._add_to_queue(address, depth)

        # Block until exploration is complete
        await self._completion_event.wait()

        # Label the initial address as "Initial" in Neo4j
        await self.neo4j_client.set_node_label(address, "Initial")

        logger.info("=" * 60)
        logger.info("Fully explored %s", address)
        logger.info("Total addresses discovered: %d", len(self.known))
        logger.info("=" * 60)

    async def visit_node(self, address: str, depth: int) -> None:
        """Queue a newly discovered address for exploration.

        Called by AddressExplorer workers when they discover a new
        counterparty address in a transaction.

        Equivalent of the Elixir NetworkExplorer.visit_node/2 function
        which sends {:add_to_queue, address, depth} to the coordinator.

        Args:
            address: The newly discovered Ethereum address.
            depth: The remaining depth for this address.
        """
        address = address.lower()
        await self._add_to_queue(address, depth)

    async def node_visited(self, address: str) -> None:
        """Signal that an address exploration is complete.

        Called by AddressExplorer workers when they finish (successfully
        or with an error).

        Equivalent of the Elixir NetworkExplorer.node_visited/1 function
        which sends {:remove_from_queue, address} to the coordinator.

        Args:
            address: The address that was just explored.
        """
        address = address.lower()
        await self._remove_from_queue(address)

    # ------------------------------------------------------------------
    # Internal queue management (mirrors Elixir handle_info callbacks)
    # ------------------------------------------------------------------

    async def _add_to_queue(self, address: str, depth: int) -> None:
        """Process a new address discovery.

        Equivalent of the Elixir {:add_to_queue, address, depth} handler:
        - If already in known → skip
        - If new + pool has room → spawn immediately
        - If new + pool full → add to remaining queue

        Args:
            address: The address to potentially explore.
            depth: The remaining depth for this address.
        """
        async with self._lock:
            # Skip if we've already seen this address
            if address in self.known:
                return

            # Mark as known so we don't process it again
            self.known.add(address)

            if self.processes_count < self.pool_size:
                # Pool has room — spawn an explorer immediately
                self._spawn_explorer(address, depth)
            else:
                # Pool is full — queue it for later
                self.remaining.append((address, depth))
                logger.debug(
                    "Pool full (%d/%d) — queued %s (queue size: %d)",
                    self.processes_count,
                    self.pool_size,
                    address,
                    len(self.remaining),
                )

    async def _remove_from_queue(self, address: str) -> None:
        """Process an explorer completion.

        Equivalent of the Elixir {:remove_from_queue, address} handler:
        - Remove from exploring set
        - If remaining has items → pop one and start it
        - If both exploring and remaining are empty → exploration complete!
        - Otherwise → just decrement process count

        Args:
            address: The address whose exploration just completed.
        """
        async with self._lock:
            self.exploring.discard(address)

            if self.remaining:
                # Pop the next address from the queue and start exploring it
                next_address, next_depth = self.remaining.popleft()
                # Note: processes_count stays the same (one finished, one started)
                self._spawn_explorer(next_address, next_depth)
                # But we need to decrement first since _spawn_explorer increments
                self.processes_count -= 1
            elif not self.exploring:
                # Both exploring and remaining are empty — we're done!
                self.processes_count = 0
                logger.info(
                    "Exploration complete! All addresses processed. "
                    "Total known: %d",
                    len(self.known),
                )
                self._completion_event.set()
            else:
                # Still some explorers running, but nothing queued
                self.processes_count -= 1
                logger.debug(
                    "Explorer finished. Active: %d, Queued: %d, Known: %d",
                    self.processes_count,
                    len(self.remaining),
                    len(self.known),
                )

    def _spawn_explorer(self, address: str, depth: int) -> None:
        """Spawn a new AddressExplorer as an asyncio task.

        Equivalent of the Elixir DynamicSupervisor.start_address_explorer/3.

        Args:
            address: The address to explore.
            depth: The remaining depth.
        """
        self.exploring.add(address)
        self.processes_count += 1

        explorer = AddressExplorer(
            eth_address=address,
            depth=depth,
            api_adapter=self.api_adapter,
            neo4j_client=self.neo4j_client,
            coordinator=self,
        )

        # Create the asyncio task (equivalent of DynamicSupervisor.start_child)
        task = asyncio.create_task(
            explorer.run(),
            name=f"explorer-{address[:10]}-d{depth}",
        )

        # Track the task so it doesn't get garbage collected
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        logger.debug(
            "Spawned explorer for %s at depth %d (%d/%d active)",
            address,
            depth,
            self.processes_count,
            self.pool_size,
        )
