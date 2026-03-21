from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


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



class ADMETResponse(BaseModel):
    success: bool
    input_smiles: str = ""
    canonical_smiles: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None
    descriptors: Optional[Dict[str, Any]] = None
    admet: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)



class ProtocolReviewRequest(BaseModel):
    protocol_text: str = Field(
        ...,
        description="Raw laboratory protocol text to review.",
        examples=[
            "Hydration of Acetylene Protocol ... Add Pt–Bi/C catalyst ... heat to 70 °C ..."
        ],
    )
    include_intermediate: bool = Field(
        default=False,
        description="If true, include outputs of individual graph branches.",
    )
    include_structured_output: bool = Field(
        default=True,
        description="If false, omit structured output from the response.",
    )


class ProtocolSectionReview(BaseModel):
    evaluation: str
    feasibility: str
    risks_or_gaps: List[str] = Field(default_factory=list)
    improvement_ideas: List[str] = Field(default_factory=list)


class ProtocolSafetyReview(BaseModel):
    hazards: List[str] = Field(default_factory=list)
    ppe: List[str] = Field(default_factory=list)
    engineering_controls: List[str] = Field(default_factory=list)
    critical_notes: List[str] = Field(default_factory=list)


class ProtocolStructuredOutput(BaseModel):
    precursor_review: ProtocolSectionReview
    steps_review: ProtocolSectionReview
    catalyst_review: ProtocolSectionReview
    reaction_conditions_review: ProtocolSectionReview
    laboratory_safety_review: ProtocolSafetyReview
    overall_summary: str
    priority_recommendations: List[str] = Field(default_factory=list)


class ProtocolIntermediateOutputs(BaseModel):
    precursor_answer: Optional[str] = None
    steps_answer: Optional[str] = None
    catalyst_answer: Optional[str] = None
    conditions_answer: Optional[str] = None
    safety_answer: Optional[str] = None
    aggregated_answer: Optional[str] = None


class ProtocolReviewResponse(BaseModel):
    success: bool
    input_protocol_text: str = ""
    final_text: Optional[str] = None
    structured_output: Optional[ProtocolStructuredOutput] = None
    intermediate: Optional[ProtocolIntermediateOutputs] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
