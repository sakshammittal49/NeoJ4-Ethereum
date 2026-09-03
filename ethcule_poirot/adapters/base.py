"""
Behaviours.Api — The API Adapter Interface Contract

Equivalent of lib/behaviours/api.ex in the Elixir project.

Defines the abstract interface that all API adapters must implement.
Any adapter (Blockscout, DissrupTheGraph, etc.) must provide all three methods.

In Python terms: this is an ABC (Abstract Base Class).
"""

from abc import ABC, abstractmethod

from ethcule_poirot.models.address import Address


class ApiAdapter(ABC):
    """Abstract base class for blockchain API adapters.

    Every adapter must implement:
        initial_setup()              — One-time configuration
        transactions_for_address()   — Fetch transactions for an address
        address_information()        — Fetch metadata about an address
    """

    @abstractmethod
    async def initial_setup(self) -> None:
        """Perform one-time setup (configure API URLs, timeouts, etc.).

        Called once before any queries are made.
        """
        ...

    @abstractmethod
    async def transactions_for_address(self, address: str) -> Address:
        """Fetch all transactions for a given address.

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address struct with populated eth_address, contract flag,
            and transactions list.
        """
        ...

    @abstractmethod
    async def address_information(self, address: str) -> Address:
        """Fetch metadata about an address (mainly: is it a smart contract?).

        Args:
            address: The Ethereum address to look up.

        Returns:
            An Address struct with populated eth_address and contract flag.
        """
        ...
