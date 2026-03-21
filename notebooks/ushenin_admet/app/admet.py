from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import math
import re

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, QED, rdMolDescriptors

_BAD_SEPARATORS_RE = re.compile(r"[.>]")
_NITRO_RE = Chem.MolFromSmarts("[NX3](=O)=O")
_ANILINE_LIKE_RE = Chem.MolFromSmarts("c[NX3;H1,H2]")
_TERTIARY_AMINE_RE = Chem.MolFromSmarts("[NX3;H0;!$(N=*);!$(N#*)]")
_HALOGEN_RE = Chem.MolFromSmarts("[F,Cl,Br,I]")
_PHENOL_RE = Chem.MolFromSmarts("c[OX2H]")


class ADMETInputError(ValueError):
    """Predictable user-facing error for invalid SMILES input."""


# ---------- Helpers ----------


def reject_mixtures_and_reactions(smiles: str) -> Optional[str]:
    # Reject mixtures: '.' ; reactions: '>' or '>>'
    if _BAD_SEPARATORS_RE.search(smiles):
        return "SMILES must represent a single molecule (no '.', '>' or '>>')."
    return None



def is_too_weird_or_empty(smiles: str) -> Optional[str]:
    s = (smiles or "").strip()
    if not s:
        return "SMILES is empty."
    if len(s) > 5000:
        return "SMILES is too long."
    return None



def canonicalize_and_descriptors(
    smiles: str, *, allow_explicit_h: bool, max_heavy_atoms: int
) -> Tuple[str, int, Dict[str, Any], Chem.Mol]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ADMETInputError("Wrong SMILES: RDKit could not parse it.")

    if not allow_explicit_h and "[H" in smiles:
        raise ADMETInputError("Explicit hydrogens are not allowed for this endpoint.")

    heavy_atoms = mol.GetNumHeavyAtoms()
    if heavy_atoms > max_heavy_atoms:
        raise ADMETInputError(
            f"Too many heavy atoms: {heavy_atoms} > {max_heavy_atoms}."
        )

    canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)
    rot = Lipinski.NumRotatableBonds(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)

    rings = rdMolDescriptors.CalcNumRings(mol)
    arom_rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    aliph_rings = rdMolDescriptors.CalcNumAliphaticRings(mol)

    frac_csp3 = rdMolDescriptors.CalcFractionCSP3(mol)
    formal_charge = Chem.GetFormalCharge(mol)

    n_atoms = mol.GetNumAtoms()
    n_hetero = rdMolDescriptors.CalcNumHeteroatoms(mol)

    mr = Crippen.MolMR(mol)

    tchi0 = Descriptors.Chi0(mol)
    tchi1 = Descriptors.Chi1(mol)
    hall_kier_alpha = Descriptors.HallKierAlpha(mol)
    kappa1 = Descriptors.Kappa1(mol)
    kappa2 = Descriptors.Kappa2(mol)
    kappa3 = Descriptors.Kappa3(mol)

    qed = float(QED.qed(mol))

    num_valence_e = Descriptors.NumValenceElectrons(mol)
    num_rad = Descriptors.NumRadicalElectrons(mol)

    aromatic_atoms = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    ap = (aromatic_atoms / heavy_atoms) if heavy_atoms > 0 else 0.0
    log_s = 0.16 - 1.5 * logp - 0.01 * (mw - 40.0) + 0.066 * rot + 0.066 * ap

    desc: Dict[str, Any] = {
        "MolWt": float(mw),
        "HeavyAtomCount": int(heavy_atoms),
        "AtomCount": int(n_atoms),
        "HeteroAtomCount": int(n_hetero),
        "FormalCharge": int(formal_charge),
        "MolLogP": float(logp),
        "TPSA": float(tpsa),
        "MolMR": float(mr),
        "HBD": int(hbd),
        "HBA": int(hba),
        "NumRotatableBonds": int(rot),
        "RingCount": int(rings),
        "AromaticRingCount": int(arom_rings),
        "AliphaticRingCount": int(aliph_rings),
        "Chi0": float(tchi0),
        "Chi1": float(tchi1),
        "HallKierAlpha": float(hall_kier_alpha),
        "Kappa1": float(kappa1),
        "Kappa2": float(kappa2),
        "Kappa3": float(kappa3),
        "FractionCSP3": float(frac_csp3),
        "QED": float(qed),
        "NumValenceElectrons": int(num_valence_e),
        "NumRadicalElectrons": int(num_rad),
        "ESOL_logS": float(log_s),
        "AromaticProportion": float(ap),
    }

    return canonical, heavy_atoms, desc, mol


# ---------- Heuristic ADMET layers ----------


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
    return {
        "label": label,
        "score": _clip01(score),
        "rationale": rationale,
    }



def _lipinski_violations(desc: Dict[str, Any]) -> int:
    violations = 0
    violations += int(desc["MolWt"] > 500)
    violations += int(desc["MolLogP"] > 5)
    violations += int(desc["HBD"] > 5)
    violations += int(desc["HBA"] > 10)
    return violations



def _has_substructure(mol: Chem.Mol, pattern: Chem.Mol | None) -> bool:
    return bool(pattern is not None and mol.HasSubstructMatch(pattern))



def heuristic_admet(mol: Chem.Mol, desc: Dict[str, Any]) -> Dict[str, Any]:
    mw = float(desc["MolWt"])
    logp = float(desc["MolLogP"])
    tpsa = float(desc["TPSA"])
    rot = int(desc["NumRotatableBonds"])
    hbd = int(desc["HBD"])
    hba = int(desc["HBA"])
    rings = int(desc["RingCount"])
    arom_rings = int(desc["AromaticRingCount"])
    charge = int(desc["FormalCharge"])
    frac_csp3 = float(desc["FractionCSP3"])
    log_s = float(desc["ESOL_logS"])
    qed = float(desc["QED"])
    heavy = int(desc["HeavyAtomCount"])

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
        - 0.04 * abs(charge)
    )
    oral_label = _bucket(oral_score)

    permeability_score = _clip01(
        0.90
        - 0.004 * max(0.0, tpsa - 60.0)
        - 0.05 * max(0.0, rot - 6)
        - 0.03 * max(0.0, hbd - 1)
        - 0.02 * abs(charge)
        - 0.08 * max(0.0, -0.5 - logp)
        - 0.06 * max(0.0, logp - 4.5)
    )
    permeability_label = _bucket(permeability_score)

    solubility_score = _clip01((log_s + 8.0) / 8.0)
    solubility_label = _label_from_thresholds(
        log_s,
        [(-6.0, "very low"), (-4.0, "low"), (-2.0, "moderate"), (999.0, "high")],
    )

    pgp_score = _clip01(
        0.10
        + 0.12 * int(mw > 450)
        + 0.12 * int(logp > 3.0)
        + 0.10 * int(rings >= 3)
        + 0.08 * int(tpsa > 90)
    )
    pgp_label = _bucket(pgp_score)

    bbb_score = _clip01(
        0.92
        - 0.006 * max(0.0, tpsa - 40.0)
        - 0.05 * max(0.0, hbd - 1)
        - 0.04 * abs(charge)
        - 0.05 * max(0.0, logp - 4.0)
        - 0.05 * max(0.0, 1.0 - logp)
    )
    bbb_label = _bucket(bbb_score)

    ppb_score = _clip01(
        0.20
        + 0.14 * int(logp > 3.0)
        + 0.12 * int(arom_rings >= 2)
        + 0.08 * int(mw > 400)
        + 0.05 * int(has_halogen)
    )
    ppb_label = _bucket(ppb_score)

    cyp3a4_score = _clip01(
        0.18
        + 0.12 * int(logp > 2.5)
        + 0.10 * int(arom_rings >= 1)
        + 0.10 * int(rings >= 2)
        + 0.10 * int(heavy > 25)
        + 0.06 * int(has_halogen)
    )
    cyp3a4_label = _bucket(cyp3a4_score)

    metabolic_stability_score = _clip01(
        0.85
        - 0.10 * int(cyp3a4_score > 0.67)
        - 0.05 * int(rot > 8)
        - 0.05 * int(logp > 4.0)
        - 0.05 * int(has_phenol)
    )
    metabolic_stability_label = _bucket(metabolic_stability_score)

    hepatic_clearance_score = _clip01(
        0.15
        + 0.18 * int(logp > 2.0)
        + 0.15 * int(cyp3a4_score > 0.5)
        + 0.08 * int(mw < 550)
    )
    hepatic_clearance_label = _bucket(hepatic_clearance_score)

    renal_clearance_score = _clip01(
        0.18
        + 0.12 * int(mw < 350)
        + 0.14 * int(logp < 1.5)
        + 0.10 * int(abs(charge) >= 1)
        + 0.10 * int(tpsa > 90)
    )
    renal_clearance_label = _bucket(renal_clearance_score)

    ames_score = _clip01(
        0.08
        + 0.30 * int(has_nitro)
        + 0.20 * int(has_aniline)
        + 0.06 * int(arom_rings >= 2)
    )
    ames_label = _bucket(ames_score)

    herg_score = _clip01(
        0.10
        + 0.18 * int(logp > 3.0)
        + 0.16 * int(has_tertiary_amine)
        + 0.12 * int(arom_rings >= 2)
        + 0.08 * int(mw > 400)
    )
    herg_label = _bucket(herg_score)

    dili_score = _clip01(
        0.10
        + 0.16 * int(logp > 3.0)
        + 0.12 * int(cyp3a4_score > 0.5)
        + 0.10 * int(mw > 400)
        + 0.08 * int(has_phenol)
        + 0.06 * int(has_aniline)
    )
    dili_label = _bucket(dili_score)

    bioavailability_score = _clip01((oral_score + permeability_score + solubility_score) / 3.0)
    bioavailability_label = _bucket(bioavailability_score)

    druglikeness_score = _clip01((max(0.0, 1.0 - 0.2 * lipinski) + qed) / 2.0)
    druglikeness_label = _bucket(druglikeness_score)

    rules_summary = {
        "model_type": "descriptor-based heuristic proxy",
        "warnings": [
            "These are rule-based ADMET proxy predictions derived from RDKit descriptors, not validated wet-lab measurements.",
            "Use this service for screening, ranking, or agent tooling, not as a sole decision-making source.",
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

    return {
        "absorption": {
            "oral_absorption": _prediction(
                oral_label,
                oral_score,
                f"Driven by MW={mw:.1f}, TPSA={tpsa:.1f}, rotatable bonds={rot}, charge={charge}, and {lipinski} Lipinski violations.",
            ),
            "caco2_permeability": _prediction(
                permeability_label,
                permeability_score,
                f"Higher permeability is favored by moderate logP={logp:.2f}, lower TPSA={tpsa:.1f}, HBD={hbd}, and fewer flexible bonds ({rot}).",
            ),
            "aqueous_solubility": _prediction(
                solubility_label,
                solubility_score,
                f"Estimated from ESOL logS={log_s:.2f}; logP={logp:.2f} and MW={mw:.1f} dominate the trend.",
            ),
            "p_gp_efflux_risk": _prediction(
                pgp_label,
                pgp_score,
                f"Risk increases with larger size (MW={mw:.1f}), lipophilicity (logP={logp:.2f}), ring count={rings}, and TPSA={tpsa:.1f}.",
            ),
            "oral_bioavailability_proxy": _prediction(
                bioavailability_label,
                bioavailability_score,
                "Combined proxy from oral absorption, permeability, and solubility heuristics.",
            ),
        },
        "distribution": {
            "bbb_penetration": _prediction(
                bbb_label,
                bbb_score,
                f"BBB penetration is favored by lower TPSA={tpsa:.1f}, HBD={hbd}, neutral charge, and moderate logP={logp:.2f}.",
            ),
            "plasma_protein_binding_risk": _prediction(
                ppb_label,
                ppb_score,
                f"Binding tendency increases with logP={logp:.2f}, aromatic ring count={arom_rings}, and MW={mw:.1f}.",
            ),
        },
        "metabolism": {
            "cyp3a4_liability": _prediction(
                cyp3a4_label,
                cyp3a4_score,
                f"Liability is increased by lipophilicity (logP={logp:.2f}), aromaticity, size ({heavy} heavy atoms), and ring count={rings}.",
            ),
            "metabolic_stability": _prediction(
                metabolic_stability_label,
                metabolic_stability_score,
                f"Stability decreases with higher CYP liability, high flexibility (rot={rot}), and reactive phenol-like motifs.",
            ),
        },
        "excretion": {
            "hepatic_clearance_tendency": _prediction(
                hepatic_clearance_label,
                hepatic_clearance_score,
                f"Tends upward with higher logP={logp:.2f} and CYP-mediated metabolism liability.",
            ),
            "renal_clearance_tendency": _prediction(
                renal_clearance_label,
                renal_clearance_score,
                f"Tends upward for smaller, more polar or charged molecules (MW={mw:.1f}, TPSA={tpsa:.1f}, charge={charge}).",
            ),
        },
        "toxicity": {
            "ames_mutagenicity_risk": _prediction(
                ames_label,
                ames_score,
                f"Raised by nitro/aniline-like motifs and aromaticity; detected nitro={has_nitro}, aniline_like={has_aniline}.",
            ),
            "herg_block_risk": _prediction(
                herg_label,
                herg_score,
                f"Risk increases with lipophilicity (logP={logp:.2f}), aromaticity, tertiary amines, and higher MW={mw:.1f}.",
            ),
            "dili_risk": _prediction(
                dili_label,
                dili_score,
                f"Risk proxy rises with lipophilicity, CYP liability, larger size, and some alerting motifs (phenol/aniline-like).",
            ),
        },
        "medicinal_chemistry": {
            "druglikeness": _prediction(
                druglikeness_label,
                druglikeness_score,
                f"Based on QED={qed:.3f} and {lipinski} Lipinski violations. FractionCSP3={frac_csp3:.3f} can also help interpretation.",
            ),
        },
        "rules_summary": rules_summary,
    }



def predict_admet(
    smiles: str,
    *,
    allow_explicit_h: bool = False,
    max_heavy_atoms: int = 200,
) -> Dict[str, Any]:
    input_smiles = smiles or ""
    warnings: List[str] = []

    err = is_too_weird_or_empty(input_smiles)
    if err:
        raise ADMETInputError(err)

    s = input_smiles.strip()
    err = reject_mixtures_and_reactions(s)
    if err:
        raise ADMETInputError(err)

    canonical, heavy_atoms, desc, mol = canonicalize_and_descriptors(
        s,
        allow_explicit_h=allow_explicit_h,
        max_heavy_atoms=max_heavy_atoms,
    )

    if any(ch in canonical for ch in "@/\\"):
        warnings.append(
            "Input contains stereochemistry or directional bonds; canonical SMILES preserves this information."
        )

    admet = heuristic_admet(mol, desc)

    return {
        "input_smiles": s,
        "canonical_smiles": canonical,
        "heavy_atoms": heavy_atoms,
        "warnings": warnings,
        "descriptors": desc,
        "admet": admet,
    }
