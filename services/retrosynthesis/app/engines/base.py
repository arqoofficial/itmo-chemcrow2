"""Abstract base class for retrosynthesis engines.

To add a new engine (e.g. DirectMultiStep):
  1. Subclass RetrosynthesisEngine
  2. Implement all abstract methods
  3. Register in ENGINES dict in app/main.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RetrosynthesisEngine(ABC):
    """Interface every retrosynthesis back-end must implement."""

    @abstractmethod
    def run_multi_step(
        self,
        smiles: str,
        *,
        max_transforms: int,
        time_limit: int,
        iterations: int,
        expansion_model: str,
        stock: str,
    ) -> dict[str, Any]:
        """Run multi-step retrosynthesis (tree search).

        Must return a dict with at least:
          - smiles, parameters, statistics, routes
        """
        ...

    @abstractmethod
    def get_resources(self) -> dict[str, list[str]]:
        """Return available expansion models and stocks.

        Expected shape: {"expansion_models": [...], "stocks": [...]}
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine identifier (e.g. 'aizynthfinder')."""
        ...
