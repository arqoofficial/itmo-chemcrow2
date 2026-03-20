"""Chemical safety tools.

Ported from chemcrow v1. Checks molecules against controlled chemicals
databases and GHS classifications.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import requests
from langchain.tools import tool

from app.tools.utils import is_smiles, pubchem_query2smiles, tanimoto

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_controlled_chemicals() -> pd.DataFrame:
    return pd.read_csv(_DATA_DIR / "chem_wep_smi.csv")


def _ghs_classification(cas_number: str) -> list[str] | None:
    """Fetch GHS classification from PubChem for a CAS number."""
    try:
        url1 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas_number}/cids/JSON"
        cid = requests.get(url1).json()["IdentifierList"]["CID"][0]
        url2 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
        data = requests.get(url2).json()
        for section in data["Record"]["Section"]:
            if section.get("TOCHeading") == "Chemical Safety":
                ghs = [
                    markup["Extra"]
                    for markup in section["Information"][0]["Value"][
                        "StringWithMarkup"
                    ][0]["Markup"]
                ]
                if ghs:
                    return ghs
    except (KeyError, requests.RequestException):
        logger.exception("Failed to fetch GHS classification for %s", cas_number)
    return None


@tool
def similar_control_chem_check(smiles: str) -> str:
    """Input SMILES, returns similarity to controlled chemicals.

    Args:
        smiles: A valid SMILES string.
    """
    if not is_smiles(smiles):
        return "Please input a valid SMILES string."

    cw_df = _load_controlled_chemicals()
    try:
        def _safe_tanimoto(s1: str, s2: str) -> float:
            sim = tanimoto(s1, s2)
            return sim if isinstance(sim, float) else 0.0

        max_sim = cw_df["smiles"].apply(lambda x: _safe_tanimoto(smiles, x)).max()
        if max_sim > 0.35:
            return (
                f"{smiles} has a high similarity "
                f"({max_sim:.4f}) to a known controlled chemical."
            )
        return (
            f"{smiles} has a low similarity "
            f"({max_sim:.4f}) to a known controlled chemical. "
            "This substance is safe, you may proceed with the task."
        )
    except Exception:
        logger.exception("Error in similar_control_chem_check")
        return "Tool error."


@tool
def control_chem_check(query: str) -> str:
    """Input CAS number or SMILES, checks if molecule is a controlled chemical.

    Args:
        query: A CAS number (e.g. '10025-87-3') or SMILES string.
    """
    cw_df = _load_controlled_chemicals()
    try:
        if is_smiles(query):
            query_esc = re.escape(query)
            found = (
                cw_df["smiles"]
                .astype(str)
                .str.contains(f"^{query_esc}$", regex=True)
                .any()
            )
        else:
            found = (
                cw_df["cas"]
                .astype(str)
                .str.contains(rf"^\({re.escape(query)}\)$", regex=True)
                .any()
            )
        if found:
            return (
                f"The molecule {query} appears in a list of controlled chemicals."
            )
        # If not found directly, check similarity
        try:
            smi = query if is_smiles(query) else pubchem_query2smiles(query)
        except ValueError as e:
            return str(e)
        return similar_control_chem_check.invoke(smi)

    except Exception as e:
        return f"Error: {e}"


@tool
def explosive_check(cas_number: str) -> str:
    """Input CAS number, returns if molecule is explosive.

    Args:
        cas_number: A CAS number (e.g. '118-96-7' for TNT).
    """
    if is_smiles(cas_number):
        return "Please input a valid CAS number."
    cls = _ghs_classification(cas_number)
    if cls is None:
        return (
            "Explosive Check Error. The molecule may not be assigned a GHS rating."
        )
    if "Explos" in str(cls) or "explos" in str(cls):
        return "Molecule is explosive"
    return "Molecule is not known to be explosive"
