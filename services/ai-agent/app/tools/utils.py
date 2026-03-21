"""Shared chemistry utility functions.

Ported from chemcrow v1 (ur-whitelab/chemcrow-public).
"""
from __future__ import annotations

import logging
import re

import requests
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem

logger = logging.getLogger(__name__)


def is_smiles(text: str) -> bool:
    """Check if text is a valid SMILES string (with chemical validation)."""
    if not text:
        return False
    try:
        m = Chem.MolFromSmiles(text, sanitize=False)
        if m is None:
            return False
        Chem.SanitizeMol(m)
        return True
    except Exception:
        return False


def is_multiple_smiles(text: str) -> bool:
    """Check if text contains multiple SMILES separated by '.'."""
    if is_smiles(text):
        return "." in text
    return False


def split_smiles(text: str) -> list[str]:
    """Split a multi-molecule SMILES string."""
    return text.split(".")


def is_cas(text: str) -> bool:
    """Check if text matches CAS number format."""
    pattern = r"^\d{2,7}-\d{2}-\d$"
    return re.match(pattern, text) is not None


def largest_mol(smiles: str) -> str:
    """Return the largest molecule from a dot-separated SMILES."""
    ss = smiles.split(".")
    ss.sort(key=lambda a: len(a))
    while not is_smiles(ss[-1]):
        rm = ss[-1]
        ss.remove(rm)
    return ss[-1]


def canonical_smiles(smiles: str) -> str:
    """Return canonical SMILES or error string."""
    try:
        smi = Chem.MolToSmiles(Chem.MolFromSmiles(smiles), canonical=True)
        return smi
    except Exception:
        return "Invalid SMILES string"


def tanimoto(s1: str, s2: str) -> float | str:
    """Calculate Tanimoto similarity between two SMILES strings."""
    try:
        mol1 = Chem.MolFromSmiles(s1)
        mol2 = Chem.MolFromSmiles(s2)
        fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, 2, nBits=2048)
        fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, 2, nBits=2048)
        return DataStructs.TanimotoSimilarity(fp1, fp2)
    except (TypeError, ValueError, AttributeError):
        return "Error: Not a valid SMILES string"


def pubchem_query2smiles(
    query: str,
    url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/{}",
) -> str:
    """Query PubChem for SMILES by molecule name or pass through valid SMILES."""
    if is_smiles(query):
        if not is_multiple_smiles(query):
            return query
        raise ValueError(
            "Multiple SMILES strings detected, input one molecule at a time."
        )
    if url is None:
        url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/{}"
    r = requests.get(url.format(query, "property/IsomericSMILES/JSON"), timeout=60)
    data = r.json()
    try:
        props = data["PropertyTable"]["Properties"][0]
        smi = props.get("IsomericSMILES") or props.get("SMILES")
    except KeyError:
        return (
            "Could not find a molecule matching the text. "
            "One possible cause is that the input is incorrect, "
            "input one molecule at a time."
        )
    return str(Chem.CanonSmiles(largest_mol(smi)))


def query2cas(query: str, url_cid: str, url_data: str) -> str:
    """Query PubChem for CAS number by molecule name or SMILES."""
    try:
        mode = "name"
        if is_smiles(query):
            if is_multiple_smiles(query):
                raise ValueError(
                    "Multiple SMILES strings detected, input one molecule at a time."
                )
            mode = "smiles"
        url_cid = url_cid.format(mode, query)
        cid = requests.get(url_cid, timeout=60).json()["IdentifierList"]["CID"][0]
        url_data = url_data.format(cid)
        data = requests.get(url_data, timeout=60).json()
    except (requests.exceptions.RequestException, KeyError):
        raise ValueError("Invalid molecule input, no Pubchem entry")

    try:
        for section in data["Record"]["Section"]:
            if section.get("TOCHeading") == "Names and Identifiers":
                for subsection in section["Section"]:
                    if subsection.get("TOCHeading") == "Other Identifiers":
                        for subsubsection in subsection["Section"]:
                            if subsubsection.get("TOCHeading") == "CAS":
                                return subsubsection["Information"][0]["Value"][
                                    "StringWithMarkup"
                                ][0]["String"]
    except KeyError:
        raise ValueError("Invalid molecule input, no Pubchem entry")

    raise ValueError("CAS number not found")


def smiles2name(smi: str, single_name: bool = True) -> str:
    """Query PubChem for molecule name by SMILES."""
    try:
        smi = Chem.MolToSmiles(Chem.MolFromSmiles(smi), canonical=True)
    except Exception:
        raise ValueError("Invalid SMILES string")
    r = requests.get(
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/"
        + smi
        + "/synonyms/JSON",
        timeout=60,
    )
    data = r.json()
    try:
        if single_name:
            index = 0
            names = data["InformationList"]["Information"][0]["Synonym"]
            while is_cas(name := names[index]):
                index += 1
                if index == len(names):
                    raise ValueError("No name found")
        else:
            name = data["InformationList"]["Information"][0]["Synonym"]
    except KeyError:
        raise ValueError("Unknown Molecule")
    return name
