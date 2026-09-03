"""
EthculePoirot — Main Entry Point

Equivalent of lib/ethcule_poirot/application.ex in the Elixir project.

This is the boot sequence. In Elixir, the Application module starts two
supervisor trees (Neo4j.Supervisor and EthculePoirot.DynamicSupervisor).

In Python, this module:
1. Initializes the Neo4j client (connects to the database)
2. Creates the API adapter (Blockscout by default)
3. Creates the NetworkExplorer coordinator
4. Kicks off the exploration
5. Cleans up on exit

Usage:
    python -m ethcule_poirot --address 0xABC... --depth 2
    python -m ethcule_poirot --address 0xABC... --depth 3 --adapter dissrup
    python -m ethcule_poirot --address 0xABC... --depth 1 --clear-db
"""

import argparse
import asyncio
import logging
import sys

from ethcule_poirot import config
from ethcule_poirot.neo4j_client.client import Neo4jClient
from ethcule_poirot.exploration.network_explorer import NetworkExplorer
from ethcule_poirot.adapters.blockscout import BlockscoutAdapter
from ethcule_poirot.adapters.dissrup_the_graph import DissrupTheGraphAdapter
from ethcule_poirot.adapters.base import ApiAdapter


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging format and level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_adapter(adapter_name: str) -> ApiAdapter:
    """Create an API adapter instance by name.

    Args:
        adapter_name: "blockscout" or "dissrup".

    Returns:
        An ApiAdapter instance.

    Raises:
        ValueError: If the adapter name is not recognized.
    """
    adapters = {
        "blockscout": BlockscoutAdapter,
        "dissrup": DissrupTheGraphAdapter,
    }
    adapter_cls = adapters.get(adapter_name.lower())
    if not adapter_cls:
        raise ValueError(
            f"Unknown adapter: {adapter_name!r}. "
            f"Available: {', '.join(adapters.keys())}"
        )
    return adapter_cls()


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="ethcule_poirot",
        description=(
            "Ethcule Poirot — Blockchain Investigation Tool. "
            "Recursively crawls Ethereum wallet transactions and builds "
            "a graph in Neo4j for analysis."
        ),
    )
    parser.add_argument(
        "--address",
        required=True,
        help="The Ethereum wallet address to start exploring (e.g., 0xABC...)",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=2,
        help="How many levels deep to explore (default: 2)",
    )
    parser.add_argument(
        "--adapter",
        default=config.DEFAULT_API_ADAPTER,
        choices=["blockscout", "dissrup"],
        help=f"Which API adapter to use (default: {config.DEFAULT_API_ADAPTER})",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=config.POOL_SIZE,
        help=f"Max concurrent explorer tasks (default: {config.POOL_SIZE})",
    )
    parser.add_argument(
        "--clear-db",
        action="store_true",
        help="Clear the Neo4j database before starting",
    )
    parser.add_argument(
        "--create-indexes",
        action="store_true",
        help="Create Neo4j indexes before starting",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    """Main async entry point.

    Orchestrates the full lifecycle:
    1. Connect to Neo4j
    2. Optionally clear database and create indexes
    3. Run the exploration
    4. Clean up
    """
    # Initialize Neo4j client (equivalent of Neo4j.Supervisor starting Bolt.Sips + Neo4j.Client)
    neo4j_client = Neo4jClient()
    await neo4j_client.connect()

    # Create the API adapter
    api_adapter = _get_adapter(args.adapter)

    try:
        # Optional: clear the database (full reset)
        if args.clear_db:
            await neo4j_client.clear_database()

        # Optional: create indexes for fast lookups
        if args.create_indexes:
            await neo4j_client.create_indexes()

        # Create the NetworkExplorer coordinator
        # (equivalent of EthculePoirot.DynamicSupervisor starting NetworkExplorer)
        explorer = NetworkExplorer(
            neo4j_client=neo4j_client,
            api_adapter=api_adapter,
            pool_size=args.pool_size,
        )

        # Start the exploration (blocks until complete)
        await explorer.explore(args.address, args.depth)

    finally:
        # Clean up resources
        if hasattr(api_adapter, "close"):
            await api_adapter.close()
        await neo4j_client.close()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    _setup_logging(args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("Ethcule Poirot — Blockchain Investigation Tool")
    logger.info("Address: %s | Depth: %d | Adapter: %s", args.address, args.depth, args.adapter)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Exploration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
