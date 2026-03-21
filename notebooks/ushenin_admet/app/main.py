from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.admet import ADMETInputError, predict_admet
from app.schemas import ADMETRequest, ADMETResponse

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



def _meta() -> Dict[str, Any]:
    return {
        "service": "admet-microservice",
        "version": __version__,
        "prediction_kind": "descriptor-based heuristic proxy",
        "notes": [
            "Predictions are descriptor-derived heuristics, not validated experimental measurements.",
            "Use for screening, ranking, and agent tooling.",
        ],
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
        meta=_meta(),
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
            meta=_meta(),
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        return ADMETResponse(
            success=False,
            input_smiles=payload.smiles,
            error={"code": "internal_error", "message": str(exc)},
            meta=_meta(),
        )

    descriptors = result["descriptors"] if payload.include_descriptors else None

    return ADMETResponse(
        success=True,
        input_smiles=result["input_smiles"],
        canonical_smiles=result["canonical_smiles"],
        warnings=result["warnings"],
        descriptors=descriptors,
        admet=result["admet"],
        meta=_meta(),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    try:
        body = await request.json()
        input_smiles = body.get("smiles", "") if isinstance(body, dict) else ""
    except Exception:
        input_smiles = ""

    return _response_error(
        status_code=422,
        input_smiles=input_smiles,
        code="request_validation_error",
        message="Request body validation failed.",
        details={"errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    try:
        body = await request.json()
        input_smiles = body.get("smiles", "") if isinstance(body, dict) else ""
    except Exception:
        input_smiles = ""

    return _response_error(
        status_code=500,
        input_smiles=input_smiles,
        code="unhandled_exception",
        message=str(exc),
    )
