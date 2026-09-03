"""
Transaction — A Single Ethereum Transaction

Equivalent of the Elixir Transaction struct. All five fields are required.

Fields:
    hash         — Unique transaction ID on the blockchain ("0xDEF...")
    to_address   — Recipient address ("0x123...")
    from_address — Sender address ("0x456...")
    value        — Amount of ETH transferred, as a string ("1.5")
    status       — Whether the transaction succeeded ("OK")
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    """Represents a single Ethereum transaction.

    All fields are required — you cannot create a Transaction
    without providing every one of them.

    Frozen=True makes instances immutable (like Elixir structs).
    """

    hash: str
    to_address: str
    from_address: str
    value: str
    status: str
