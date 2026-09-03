"""
Address — The Wallet/Contract Representation

Equivalent of the Elixir Address struct.

Fields:
    eth_address  — The Ethereum address string ("0xABC...")
    contract     — Whether this is a smart contract (True) or regular wallet (False)
    transactions — List of Transaction structs associated with this address
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ethcule_poirot.models.transaction import Transaction


@dataclass
class Address:
    """Represents an Ethereum address (wallet or smart contract).

    Unlike Transaction, fields here are optional — an Address can be
    partially populated depending on the context (e.g., we may know the
    address string but haven't yet determined if it's a contract).
    """

    eth_address: str | None = None
    contract: bool | None = None
    transactions: list[Transaction] = field(default_factory=list)
