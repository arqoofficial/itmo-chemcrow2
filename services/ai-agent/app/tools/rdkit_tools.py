"""RDKit-based molecular property tools.

Ported from chemcrow v1.
"""
from __future__ import annotations

from langchain.tools import tool
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from app.tools.utils import tanimoto


@tool
def smiles2weight(smiles: str) -> str:
    """Input SMILES, returns molecular weight.

    Args:
        smiles: A valid SMILES string representing a molecule.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "Invalid SMILES string"
    mol_weight = rdMolDescriptors.CalcExactMolWt(mol)
    return str(round(mol_weight, 4))


@tool
def mol_similarity(smiles1: str, smiles2: str) -> str:
    """Compare two molecules by Tanimoto similarity.

    Args:
        smiles1: SMILES string of the first molecule.
        smiles2: SMILES string of the second molecule.
    """
    similarity = tanimoto(smiles1, smiles2)

    if isinstance(similarity, str):
        return similarity

    if similarity == 1:
        return "Error: Input Molecules Are Identical"

    sim_score = {
        0.9: "very similar",
        0.8: "similar",
        0.7: "somewhat similar",
        0.6: "not very similar",
        0: "not similar",
    }
    val = sim_score[max(key for key in sim_score if key <= round(similarity, 1))]
    return (
        f"The Tanimoto similarity between {smiles1} and {smiles2} is "
        f"{round(similarity, 4)}, indicating that the two molecules are {val}."
    )


# Functional group SMARTS patterns
_FUNCTIONAL_GROUPS = {
    "furan": "o1cccc1",
    "aldehydes": " [CX3H1](=O)[#6]",
    "esters": " [#6][CX3](=O)[OX2H0][#6]",
    "ketones": " [#6][CX3](=O)[#6]",
    "amides": " C(=O)-N",
    "thiol groups": " [SH]",
    "alcohol groups": " [OH]",
    "methylamide": "*-[N;D2]-[C;D3](=O)-[C;D1;H3]",
    "carboxylic acids": "*-C(=O)[O;D1]",
    "carbonyl methylester": "*-C(=O)[O;D2]-[C;D1;H3]",
    "terminal aldehyde": "*-C(=O)-[C;D1]",
    "amide": "*-C(=O)-[N;D1]",
    "carbonyl methyl": "*-C(=O)-[C;D1;H3]",
    "isocyanate": "*-[N;D2]=[C;D2]=[O;D1]",
    "isothiocyanate": "*-[N;D2]=[C;D2]=[S;D1]",
    "nitro": "*-[N;D3](=[O;D1])[O;D1]",
    "nitroso": "*-[N;R0]=[O;D1]",
    "oximes": "*=[N;R0]-[O;D1]",
    "Imines": "*-[N;R0]=[C;D1;H2]",
    "terminal azo": "*-[N;D2]=[N;D2]-[C;D1;H3]",
    "hydrazines": "*-[N;D2]=[N;D1]",
    "diazo": "*-[N;D2]#[N;D1]",
    "cyano": "*-[C;D2]#[N;D1]",
    "primary sulfonamide": "*-[S;D4](=[O;D1])(=[O;D1])-[N;D1]",
    "methyl sulfonamide": "*-[N;D2]-[S;D4](=[O;D1])(=[O;D1])-[C;D1;H3]",
    "sulfonic acid": "*-[S;D4](=O)(=O)-[O;D1]",
    "methyl ester sulfonyl": "*-[S;D4](=O)(=O)-[O;D2]-[C;D1;H3]",
    "methyl sulfonyl": "*-[S;D4](=O)(=O)-[C;D1;H3]",
    "sulfonyl chloride": "*-[S;D4](=O)(=O)-[Cl]",
    "methyl sulfinyl": "*-[S;D3](=O)-[C;D1]",
    "methyl thio": "*-[S;D2]-[C;D1;H3]",
    "thiols": "*-[S;D1]",
    "thio carbonyls": "*=[S;D1]",
    "halogens": "*-[#9,#17,#35,#53]",
    "t-butyl": "*-[C;D4]([C;D1])([C;D1])-[C;D1]",
    "tri fluoromethyl": "*-[C;D4](F)(F)F",
    "acetylenes": "*-[C;D2]#[C;D1;H]",
    "cyclopropyl": "*-[C;D3]1-[C;D2]-[C;D2]1",
    "ethoxy": "*-[O;D2]-[C;D2]-[C;D1;H3]",
    "methoxy": "*-[O;D2]-[C;D1;H3]",
    "side-chain hydroxyls": "*-[O;D1]",
    "ketones_generic": "*=[O;D1]",
    "primary amines": "*-[N;D1]",
    "nitriles": "*#[N;D1]",
}


def _is_fg_in_mol(mol_smiles: str, fg_smarts: str) -> bool:
    fgmol = Chem.MolFromSmarts(fg_smarts.strip())
    mol = Chem.MolFromSmiles(mol_smiles.strip())
    return len(Chem.Mol.GetSubstructMatches(mol, fgmol, uniquify=True)) > 0


@tool
def func_groups(smiles: str) -> str:
    """Input SMILES, return list of functional groups in the molecule.

    Args:
        smiles: A valid SMILES string representing a molecule.
    """
    try:
        fgs_in_molec = [
            name
            for name, fg in _FUNCTIONAL_GROUPS.items()
            if _is_fg_in_mol(smiles, fg)
        ]
        if len(fgs_in_molec) > 1:
            return f"This molecule contains {', '.join(fgs_in_molec[:-1])}, and {fgs_in_molec[-1]}."
        elif len(fgs_in_molec) == 1:
            return f"This molecule contains {fgs_in_molec[0]}."
        else:
            return "No known functional groups found."
    except Exception:
        return "Wrong argument. Please input a valid molecular SMILES."
