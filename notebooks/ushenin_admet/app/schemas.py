from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ADMETRequest(BaseModel):
    smiles: str = Field(
        default="",
        description="Single-molecule SMILES string. Mixtures and reaction SMILES are rejected.",
        examples=["CC(=O)Oc1ccccc1C(=O)O"],
    )
    allow_explicit_h: bool = Field(
        default=False,
        description="Allow explicit hydrogen tokens like [H].",
    )
    max_heavy_atoms: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Upper bound for heavy atoms. Large molecules are rejected for safety and latency reasons.",
    )
    include_descriptors: bool = Field(
        default=True,
        description="If false, omit RDKit descriptor block from the response.",
    )


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ADMETResponse(BaseModel):
    success: bool
    input_smiles: str = ""
    canonical_smiles: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None
    descriptors: Optional[Dict[str, Any]] = None
    admet: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
