"""ADMET prediction tool based on RDKit descriptors and heuristic rules."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain.tools import tool
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, QED, rdMolDescriptors

_BAD_SEPARATORS_RE = re.compile(r"[.>]")
_NITRO_RE = Chem.MolFromSmarts("[NX3](=O)=O")
_ANILINE_LIKE_RE = Chem.MolFromSmarts("c[NX3;H1,H2]")
_TERTIARY_AMINE_RE = Chem.MolFromSmarts("[NX3;H0;!$(N=*);!$(N#*)]")
_HALOGEN_RE = Chem.MolFromSmarts("[F,Cl,Br,I]")
_PHENOL_RE = Chem.MolFromSmarts("c[OX2H]")


def _clip01(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _bucket(score: float, *, low: float = 0.34, high: float = 0.67) -> str:
    if score >= high:
        return "high"
    if score <= low:
        return "low"
    return "medium"


def _label_from_thresholds(value: float, thresholds: List[Tuple[float, str]]) -> str:
    for limit, label in thresholds:
        if value <= limit:
            return label
    return thresholds[-1][1]


def _prediction(label: str, score: float, rationale: str) -> Dict[str, Any]:
    return {"label": label, "score": _clip01(score), "rationale": rationale}


def _lipinski_violations(desc: Dict[str, Any]) -> int:
    violations = 0
    violations += int(desc["MolWt"] > 500)
    violations += int(desc["MolLogP"] > 5)
    violations += int(desc["HBD"] > 5)
    violations += int(desc["HBA"] > 10)
    return violations


def _has_substructure(mol: Chem.Mol, pattern: Optional[Chem.Mol]) -> bool:
    return bool(pattern is not None and mol.HasSubstructMatch(pattern))


def _predict_admet(smiles: str) -> Dict[str, Any]:
    s = (smiles or "").strip()
    if not s:
        raise ValueError("SMILES is empty.")
    if len(s) > 5000:
        raise ValueError("SMILES is too long.")
    if _BAD_SEPARATORS_RE.search(s):
        raise ValueError("SMILES must represent a single molecule (no '.', '>' or '>>').")

    mol = Chem.MolFromSmiles(s)
    if mol is None:
        raise ValueError("Wrong SMILES: RDKit could not parse it.")

    heavy = mol.GetNumHeavyAtoms()
    if heavy > 200:
        raise ValueError(f"Too many heavy atoms: {heavy} > 200.")

    canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    rot = Lipinski.NumRotatableBonds(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)
    rings = rdMolDescriptors.CalcNumRings(mol)
    arom_rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    frac_csp3 = rdMolDescriptors.CalcFractionCSP3(mol)
    formal_charge = Chem.GetFormalCharge(mol)
    n_hetero = rdMolDescriptors.CalcNumHeteroatoms(mol)
    qed = float(QED.qed(mol))

    aromatic_atoms = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    ap = (aromatic_atoms / heavy) if heavy > 0 else 0.0
    log_s = 0.16 - 1.5 * logp - 0.01 * (mw - 40.0) + 0.066 * rot + 0.066 * ap

    desc: Dict[str, Any] = {
        "MolWt": float(mw),
        "HeavyAtomCount": int(heavy),
        "HeteroAtomCount": int(n_hetero),
        "FormalCharge": int(formal_charge),
        "MolLogP": float(logp),
        "TPSA": float(tpsa),
        "HBD": int(hbd),
        "HBA": int(hba),
        "NumRotatableBonds": int(rot),
        "RingCount": int(rings),
        "AromaticRingCount": int(arom_rings),
        "FractionCSP3": float(frac_csp3),
        "QED": float(qed),
        "ESOL_logS": float(log_s),
        "AromaticProportion": float(ap),
    }

    lipinski = _lipinski_violations(desc)
    has_nitro = _has_substructure(mol, _NITRO_RE)
    has_aniline = _has_substructure(mol, _ANILINE_LIKE_RE)
    has_tertiary_amine = _has_substructure(mol, _TERTIARY_AMINE_RE)
    has_halogen = _has_substructure(mol, _HALOGEN_RE)
    has_phenol = _has_substructure(mol, _PHENOL_RE)

    oral_score = _clip01(
        1.0
        - 0.20 * lipinski
        - 0.002 * max(0.0, mw - 350.0)
        - 0.003 * max(0.0, tpsa - 90.0)
        - 0.04 * max(0.0, rot - 8)
        - 0.04 * abs(formal_charge)
    )

    permeability_score = _clip01(
        0.90
        - 0.004 * max(0.0, tpsa - 60.0)
        - 0.05 * max(0.0, rot - 6)
        - 0.03 * max(0.0, hbd - 1)
        - 0.02 * abs(formal_charge)
        - 0.08 * max(0.0, -0.5 - logp)
        - 0.06 * max(0.0, logp - 4.5)
    )

    solubility_score = _clip01((log_s + 8.0) / 8.0)
    solubility_label = _label_from_thresholds(
        log_s, [(-6.0, "very low"), (-4.0, "low"), (-2.0, "moderate"), (999.0, "high")]
    )

    pgp_score = _clip01(
        0.10
        + 0.12 * int(mw > 450)
        + 0.12 * int(logp > 3.0)
        + 0.10 * int(rings >= 3)
        + 0.08 * int(tpsa > 90)
    )

    bbb_score = _clip01(
        0.92
        - 0.006 * max(0.0, tpsa - 40.0)
        - 0.05 * max(0.0, hbd - 1)
        - 0.04 * abs(formal_charge)
        - 0.05 * max(0.0, logp - 4.0)
        - 0.05 * max(0.0, 1.0 - logp)
    )

    ppb_score = _clip01(
        0.20
        + 0.14 * int(logp > 3.0)
        + 0.12 * int(arom_rings >= 2)
        + 0.08 * int(mw > 400)
        + 0.05 * int(has_halogen)
    )

    cyp3a4_score = _clip01(
        0.18
        + 0.12 * int(logp > 2.5)
        + 0.10 * int(arom_rings >= 1)
        + 0.10 * int(rings >= 2)
        + 0.10 * int(heavy > 25)
        + 0.06 * int(has_halogen)
    )

    metabolic_stability_score = _clip01(
        0.85
        - 0.10 * int(cyp3a4_score > 0.67)
        - 0.05 * int(rot > 8)
        - 0.05 * int(logp > 4.0)
        - 0.05 * int(has_phenol)
    )

    hepatic_clearance_score = _clip01(
        0.15
        + 0.18 * int(logp > 2.0)
        + 0.15 * int(cyp3a4_score > 0.5)
        + 0.08 * int(mw < 550)
    )

    renal_clearance_score = _clip01(
        0.18
        + 0.12 * int(mw < 350)
        + 0.14 * int(logp < 1.5)
        + 0.10 * int(abs(formal_charge) >= 1)
        + 0.10 * int(tpsa > 90)
    )

    ames_score = _clip01(
        0.08
        + 0.30 * int(has_nitro)
        + 0.20 * int(has_aniline)
        + 0.06 * int(arom_rings >= 2)
    )

    herg_score = _clip01(
        0.10
        + 0.18 * int(logp > 3.0)
        + 0.16 * int(has_tertiary_amine)
        + 0.12 * int(arom_rings >= 2)
        + 0.08 * int(mw > 400)
    )

    dili_score = _clip01(
        0.10
        + 0.16 * int(logp > 3.0)
        + 0.12 * int(cyp3a4_score > 0.5)
        + 0.10 * int(mw > 400)
        + 0.08 * int(has_phenol)
        + 0.06 * int(has_aniline)
    )

    bioavailability_score = _clip01((oral_score + permeability_score + solubility_score) / 3.0)
    druglikeness_score = _clip01((max(0.0, 1.0 - 0.2 * lipinski) + qed) / 2.0)

    return {
        "canonical_smiles": canonical,
        "descriptors": desc,
        "admet": {
            "absorption": {
                "oral_absorption": _prediction(_bucket(oral_score), oral_score,
                    f"MW={mw:.1f}, TPSA={tpsa:.1f}, rot={rot}, charge={formal_charge}, {lipinski} Lipinski violations."),
                "caco2_permeability": _prediction(_bucket(permeability_score), permeability_score,
                    f"logP={logp:.2f}, TPSA={tpsa:.1f}, HBD={hbd}, rot={rot}."),
                "aqueous_solubility": _prediction(solubility_label, solubility_score,
                    f"ESOL logS={log_s:.2f}; logP={logp:.2f}, MW={mw:.1f}."),
                "p_gp_efflux_risk": _prediction(_bucket(pgp_score), pgp_score,
                    f"MW={mw:.1f}, logP={logp:.2f}, rings={rings}, TPSA={tpsa:.1f}."),
                "oral_bioavailability_proxy": _prediction(_bucket(bioavailability_score), bioavailability_score,
                    "Combined from oral absorption, permeability, and solubility."),
            },
            "distribution": {
                "bbb_penetration": _prediction(_bucket(bbb_score), bbb_score,
                    f"TPSA={tpsa:.1f}, HBD={hbd}, charge={formal_charge}, logP={logp:.2f}."),
                "plasma_protein_binding_risk": _prediction(_bucket(ppb_score), ppb_score,
                    f"logP={logp:.2f}, arom_rings={arom_rings}, MW={mw:.1f}."),
            },
            "metabolism": {
                "cyp3a4_liability": _prediction(_bucket(cyp3a4_score), cyp3a4_score,
                    f"logP={logp:.2f}, arom_rings={arom_rings}, heavy={heavy}, rings={rings}."),
                "metabolic_stability": _prediction(_bucket(metabolic_stability_score), metabolic_stability_score,
                    f"CYP liability={cyp3a4_score:.3f}, rot={rot}, logP={logp:.2f}, phenol={has_phenol}."),
            },
            "excretion": {
                "hepatic_clearance_tendency": _prediction(_bucket(hepatic_clearance_score), hepatic_clearance_score,
                    f"logP={logp:.2f}, CYP liability={cyp3a4_score:.3f}."),
                "renal_clearance_tendency": _prediction(_bucket(renal_clearance_score), renal_clearance_score,
                    f"MW={mw:.1f}, TPSA={tpsa:.1f}, charge={formal_charge}."),
            },
            "toxicity": {
                "ames_mutagenicity_risk": _prediction(_bucket(ames_score), ames_score,
                    f"nitro={has_nitro}, aniline_like={has_aniline}, arom_rings={arom_rings}."),
                "herg_block_risk": _prediction(_bucket(herg_score), herg_score,
                    f"logP={logp:.2f}, tertiary_amine={has_tertiary_amine}, arom_rings={arom_rings}, MW={mw:.1f}."),
                "dili_risk": _prediction(_bucket(dili_score), dili_score,
                    f"logP={logp:.2f}, CYP={cyp3a4_score:.3f}, MW={mw:.1f}, phenol={has_phenol}, aniline={has_aniline}."),
            },
            "medicinal_chemistry": {
                "druglikeness": _prediction(_bucket(druglikeness_score), druglikeness_score,
                    f"QED={qed:.3f}, {lipinski} Lipinski violations, FractionCSP3={frac_csp3:.3f}."),
            },
        },
        "warnings": [
            "Rule-based ADMET proxy predictions from RDKit descriptors, not validated wet-lab measurements.",
            "Use for screening or ranking only.",
        ],
        "lipinski_violations": lipinski,
        "feature_flags": {
            "nitro_group": has_nitro,
            "aniline_like": has_aniline,
            "tertiary_amine": has_tertiary_amine,
            "halogen": has_halogen,
            "phenol": has_phenol,
        },
    }


@tool
def smiles_to_admet(smiles: str) -> str:
    """Predict ADMET properties for a single molecule from its SMILES string.

    Returns RDKit descriptors and heuristic proxy predictions for absorption,
    distribution, metabolism, excretion, and toxicity (ADMET). Rejects mixtures
    and reaction SMILES.

    Args:
        smiles: A single-molecule SMILES string, e.g. CC(=O)Oc1ccccc1C(=O)O.
                Do not send mixtures with '.' or reaction SMILES with '>' or '>>'.
    """
    try:
        result = _predict_admet(smiles)
        return json.dumps(result, indent=2)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Unexpected error during ADMET prediction: {e}"
