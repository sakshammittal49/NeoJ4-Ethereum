"""
Configuration — Environment-based settings

Equivalent of config/config.exs in the Elixir project.
Loads configuration from environment variables (via .env file or system env).

Config keys:
    DATABASE_URL      — Neo4j connection URL (bolt://localhost:7687)
    NEO4J_USER        — Neo4j username
    NEO4J_PASSWORD    — Neo4j password
    BLOCKSCOUT_API_URL — Blockscout GraphQL API endpoint
    POOL_SIZE         — Max concurrent address explorers (default: 30)
    API_TIMEOUT       — API request timeout in milliseconds (default: 120000)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from the project root (parent of the package directory)
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


# --- Neo4j Database Connection ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

# --- Blockscout API ---
BLOCKSCOUT_API_URL: str = os.getenv(
    "BLOCKSCOUT_API_URL", "https://eth.blockscout.com/api/v1/graphql"
)

# --- Pool Configuration ---
# Max concurrent AddressExplorer tasks (equivalent of ethcule_poirot pool_size in Elixir)
POOL_SIZE: int = int(os.getenv("POOL_SIZE", "30"))

# API request timeout in seconds (env var is in milliseconds for Elixir compat)
API_TIMEOUT: float = int(os.getenv("API_TIMEOUT", "120000")) / 1000.0

# --- Default API Adapter ---
# This is set programmatically, not via env var. The Elixir config uses
# `Adapters.Api.Blockscout` as the default; we mirror that in main.py.
DEFAULT_API_ADAPTER: str = "blockscout"
