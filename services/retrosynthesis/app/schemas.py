from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MultiStepRequest(BaseModel):
    """Input for multi-step (tree-search) retrosynthesis."""

    smiles: str = Field(..., min_length=1, description="Target molecule SMILES")
    max_transforms: int = Field(default=12, ge=1, le=24, description="Max tree depth")
    time_limit: int = Field(default=10, ge=1, le=120, description="Time limit (seconds)")
    iterations: int = Field(default=100, ge=1, le=100, description="MCTS iterations")
    expansion_model: str = Field(default="uspto", description="Expansion policy name")
    stock: str = Field(default="zinc", description="Stock database name")


class MultiStepResult(BaseModel):
    """Full result of multi-step retrosynthesis."""

    smiles: str
    parameters: dict[str, Any]
    statistics: dict[str, Any]
    stock_info: dict[str, Any]
    routes: Any


class ResourcesResponse(BaseModel):
    """Available engine resources (models, stocks)."""

    expansion_models: list[str]
    stocks: list[str]
