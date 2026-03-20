"""Molecule name/SMILES/CAS conversion tools.

Ported from chemcrow v1. Uses PubChem REST API (free, no key required).
"""
from __future__ import annotations

from langchain.tools import tool

from app.tools.utils import (
    is_multiple_smiles,
    is_smiles,
    pubchem_query2smiles,
    query2cas,
    smiles2name,
)


_URL_CID = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{}/{}/cids/JSON"
_URL_DATA = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{}/JSON"


@tool
def query2smiles_tool(query: str) -> str:
    """Input a molecule name, returns SMILES.

    Args:
        query: A molecule name (e.g. 'caffeine', 'aspirin').
    """
    if is_smiles(query) and is_multiple_smiles(query):
        return "Multiple SMILES strings detected, input one molecule at a time."
    try:
        return pubchem_query2smiles(query)
    except Exception as e:
        return str(e)


@tool
def query2cas_tool(query: str) -> str:
    """Input molecule (name or SMILES), returns CAS number.

    Args:
        query: A molecule name or SMILES string.
    """
    try:
        cas = query2cas(query, _URL_CID, _URL_DATA)
        return cas
    except ValueError as e:
        return str(e)


@tool
def smiles2name_tool(query: str) -> str:
    """Input SMILES, returns molecule name.

    Args:
        query: A valid SMILES string.
    """
    try:
        if not is_smiles(query):
            try:
                query = pubchem_query2smiles(query)
            except Exception:
                raise ValueError("Invalid molecule input, no Pubchem entry")
        return smiles2name(query)
    except Exception as e:
        return "Error: " + str(e)
