"""Molecule 2D structure drawing tool using RDKit."""
from __future__ import annotations

import base64
import io
import threading

from langchain.tools import tool
from rdkit import Chem
from rdkit.Chem import AllChem, Draw

_image_store: dict[str, str] = {}
_image_lock = threading.Lock()


def pop_pending_image(smiles: str) -> str | None:
    """Retrieve and remove the pending structure image for this SMILES."""
    with _image_lock:
        return _image_store.pop(smiles, None)


def _render(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")

    AllChem.Compute2DCoords(mol)
    img = Draw.MolToImage(mol, size=(500, 350))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@tool
def draw_molecule_rdkit(smiles: str) -> str:
    """Draw the 2D structure of a molecule from its SMILES string using RDKit.

    Renders a 2D structural formula locally with atom labels and stereo annotations.

    Args:
        smiles: SMILES string of the molecule to draw.
    """
    s = (smiles or "").strip()
    if not s:
        return "Error: SMILES string is empty."

    try:
        data_uri = _render(s)
        with _image_lock:
            _image_store[s] = data_uri
        return f"Structure drawn for `{s}`."
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error drawing molecule: {e}"
