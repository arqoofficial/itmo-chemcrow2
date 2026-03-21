from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.admet import ADMETInputError, predict_admet
from app.prot_review import ProtocolReviewError, run_protocol_review

from app.schemas import *

from app.smirks_to_protocol import *

from pydantic import ValidationError
import asyncio


def _prot_review_meta() -> Dict[str, Any]:
    return {
        "service": "protocol-review-microservice",
        "version": __version__,
        "graph": "parallel-5-branch-review",
        "model": os.getenv("OPENAI_MODEL", "unknown"),
        "notes": [
            "This endpoint returns free-form chemistry protocol review text plus validated structured output.",
            "Structured output is generated from final synthesized text using a deterministic extraction pass.",
        ],
    }

APP_NAME = os.getenv("ADMET_APP_NAME", "ADMET Microservice")
DEFAULT_MAX_HEAVY_ATOMS = int(os.getenv("ADMET_MAX_HEAVY_ATOMS", "200"))
DEFAULT_ALLOW_EXPLICIT_H = os.getenv("ADMET_ALLOW_EXPLICIT_H", "false").lower() == "true"

app = FastAPI(
    title=APP_NAME,
    version=__version__,
    description=(
        "FastAPI microservice that converts a single-molecule SMILES string into "
        "RDKit descriptors plus descriptor-based heuristic ADMET proxy predictions."
    ),
)



def _admet_meta() -> Dict[str, Any]:
    return {
        "service": "admet-microservice",
        "version": __version__,
        "prediction_kind": "descriptor-based heuristic proxy",
        "notes": [
            "Predictions are descriptor-derived heuristics, not validated experimental measurements.",
            "Use for screening, ranking, and agent tooling.",
        ],
    }


def _smirks_meta() -> Dict[str, Any]:
    return {
        "service": "smirks_to_protocol",
        "version": __version__,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }



def _response_error(
    *,
    status_code: int,
    input_smiles: str,
    code: str,
    message: str,
    details: Dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ADMETResponse(
        success=False,
        input_smiles=input_smiles,
        error={"code": code, "message": message, "details": details},
        meta=_admet_meta(),
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True, "service": APP_NAME, "version": __version__}


@app.post("/v1/admet", response_model=ADMETResponse)
def admet_endpoint(payload: ADMETRequest) -> ADMETResponse:
    try:
        result = predict_admet(
            payload.smiles,
            allow_explicit_h=payload.allow_explicit_h or DEFAULT_ALLOW_EXPLICIT_H,
            max_heavy_atoms=payload.max_heavy_atoms or DEFAULT_MAX_HEAVY_ATOMS,
        )
    except ADMETInputError as exc:
        return ADMETResponse(
            success=False,
            input_smiles=payload.smiles,
            error={"code": "invalid_smiles", "message": str(exc)},
            meta=_admet_meta(),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        return ADMETResponse(
            success=False,
            input_smiles=payload.smiles,
            error={"code": "internal_error", "message": str(exc)},
            meta=_admet_meta(),
        )

    descriptors = result["descriptors"] if payload.include_descriptors else None

    return ADMETResponse(
        success=True,
        input_smiles=result["input_smiles"],
        canonical_smiles=result["canonical_smiles"],
        warnings=result["warnings"],
        descriptors=descriptors,
        admet=result["admet"],
        meta=_admet_meta(),
    )

#
# @app.exception_handler(RequestValidationError)
# async def request_validation_exception_handler(
#     request: Request,
#     exc: RequestValidationError,
# ) -> JSONResponse:
#     try:
#         body = await request.json()
#         input_smiles = body.get("smiles", "") if isinstance(body, dict) else ""
#     except Exception:
#         input_smiles = ""
#
#     return _response_error(
#         status_code=422,
#         input_smiles=input_smiles,
#         code="request_validation_error",
#         message="Request body validation failed.",
#         details={"errors": exc.errors()},
#     )


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    try:
        body = request.json()
        input_smiles = body.get("smiles", "") if isinstance(body, dict) else ""
    except Exception:
        input_smiles = ""

    return _response_error(
        status_code=500,
        input_smiles=input_smiles,
        code="unhandled_exception",
        message=str(exc),
    )


@app.post("/v1/prot_review", response_model=ProtocolReviewResponse)
def prot_review_endpoint(payload: ProtocolReviewRequest) -> ProtocolReviewResponse:
    try:
        result = run_protocol_review(
            payload.protocol_text,
            include_intermediate=payload.include_intermediate,
        )
    except ProtocolReviewError as exc:
        return ProtocolReviewResponse(
            success=False,
            input_protocol_text=payload.protocol_text,
            error={"code": "invalid_protocol_text", "message": str(exc)},
            meta=_prot_review_meta(),
        )
    except ValidationError as exc:
        return ProtocolReviewResponse(
            success=False,
            input_protocol_text=payload.protocol_text,
            error={
                "code": "structured_output_validation_error",
                "message": "Failed to validate structured protocol-review output.",
                "details": {"errors": exc.errors()},
            },
            meta=_prot_review_meta(),
        )
    except Exception as exc:  # pragma: no cover
        return ProtocolReviewResponse(
            success=False,
            input_protocol_text=payload.protocol_text,
            error={"code": "internal_error", "message": str(exc)},
            meta=_prot_review_meta(),
        )

    return ProtocolReviewResponse(
        success=True,
        input_protocol_text=result["input_protocol_text"],
        final_text=result["final_text"],
        structured_output=result["structured_output"] if payload.include_structured_output else None,
        intermediate=result.get("intermediate") if payload.include_intermediate else None,
        warnings=result.get("warnings", []),
        meta=_prot_review_meta(),
    )


def _meta() -> Dict[str, Any]:
    return {
        "service": "smirks_to_protocol",
        "version": "0.0.1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/smirks_to_protocol", response_model=SMIRKSToProtocolResponse)
async def smirks_to_protocol_endpoint(
    payload: SMIRKSToProtocolRequest,
) -> SMIRKSToProtocolResponse:
    smirks = payload.smirks.strip()

    if not smirks:
        return SMIRKSToProtocolResponse(
            success=False,
            input_smirks=payload.smirks,
            error=ErrorInfo(
                code="empty_smirks",
                message="SMIRKS must be a non-empty string.",
            ),
            meta=_smirks_meta(),
        )

    try:
        result = await asyncio.wait_for(
            run_reaction_with_council(smirks),
            timeout=120,
        )
    except asyncio.TimeoutError:
        return SMIRKSToProtocolResponse(
            success=False,
            input_smirks=smirks,
            error=ErrorInfo(
                code="timeout",
                message="Council execution timed out.",
            ),
            meta=_smirks_meta(),
        )
    except ValueError as exc:
        return SMIRKSToProtocolResponse(
            success=False,
            input_smirks=smirks,
            error=ErrorInfo(
                code="invalid_reaction_smirks",
                message=str(exc),
            ),
            meta=_smirks_meta(),
        )
    except Exception as exc:
        return SMIRKSToProtocolResponse(
            success=False,
            input_smirks=smirks,
            error=ErrorInfo(
                code="internal_error",
                message=str(exc),
            ),
            meta=_smirks_meta(),
        )

    protocol_markdown = (result.get("final_protocol_markdown") or "").strip()
    if not protocol_markdown:
        return SMIRKSToProtocolResponse(
            success=False,
            input_smirks=smirks,
            error=ErrorInfo(
                code="council_failed",
                message="Council did not produce a usable protocol.",
                details={"errors": result.get("errors", [])},
            ),
            meta=_smirks_meta(),
        )

    return SMIRKSToProtocolResponse(
        success=True,
        input_smirks=smirks,
        protocol_markdown=protocol_markdown,
        chairman_reasoning=result.get("chairman_reasoning", ""),
        uncertainty=result.get("uncertainty", ""),
        meta=_smirks_meta(),
    )

@app.exception_handler(RequestValidationError)
def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    try:
        body = request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}

    path = request.url.path

    if path == "/v1/admet":
        payload = ADMETResponse(
            success=False,
            input_smiles=body.get("smiles", ""),
            error={
                "code": "request_validation_error",
                "message": "Request body validation failed.",
                "details": {"errors": exc.errors()},
            },
            meta=_admet_meta(),
        ).model_dump(mode="json")
        return JSONResponse(status_code=422, content=payload)

    if path == "/v1/prot_review":
        payload = ProtocolReviewResponse(
            success=False,
            input_protocol_text=body.get("protocol_text", ""),
            error={
                "code": "request_validation_error",
                "message": "Request body validation failed.",
                "details": {"errors": exc.errors()},
            },
            meta=_prot_review_meta(),
        ).model_dump(mode="json")
        return JSONResponse(status_code=422, content=payload)

    if path == "/v1/smirks_to_protocol":
        payload = SMIRKSToProtocolResponse(
            success=False,
            input_smirks=body.get("smirks", ""),
            error=ErrorInfo(
                code="request_validation_error",
                message="Request body validation failed.",
                details={"errors": exc.errors()},
            ),
            meta=_smirks_meta(),
        ).model_dump(mode="json")
        return JSONResponse(status_code=422, content=payload)

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "request_validation_error",
                "message": "Request body validation failed.",
                "details": {"errors": exc.errors()},
            },
        },
    )
