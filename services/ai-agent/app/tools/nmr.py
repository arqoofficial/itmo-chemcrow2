"""1H NMR prediction tool via NMRdb.org API."""
from __future__ import annotations

import base64
import io
import threading
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import requests
from langchain.tools import tool
from rdkit import Chem
from rdkit.Chem import AllChem

_NMRDB_1H_URL = "https://www.nmrdb.org/service/predictor"
_MULT = {1: "d", 2: "t", 3: "q", 4: "quint"}

# Pending images: smiles → base64 data URI.
# Populated by the tool, consumed by main.py in on_tool_end.
_image_store: dict[str, str] = {}
_image_lock = threading.Lock()


def pop_pending_image(smiles: str) -> str | None:
    """Retrieve and remove the pending NMR spectrum image for this SMILES."""
    with _image_lock:
        return _image_store.pop(smiles, None)


def _smiles_to_molfile(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    AllChem.Compute2DCoords(mol)
    return Chem.MolToMolBlock(mol)


def _fetch_1h(smiles: str) -> str:
    molfile = _smiles_to_molfile(smiles)
    r = requests.post(_NMRDB_1H_URL, data={"molfile": molfile}, timeout=30)
    r.raise_for_status()
    return r.text


def _parse_1h(raw: str) -> list[dict]:
    atoms: list[dict] = []
    for line in raw.strip().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        shift = float(parts[2])
        n_couplings = int(parts[3])
        j_values: list[float] = []
        for i in range(n_couplings):
            base = 4 + i * 3
            if base + 2 < len(parts):
                j_values.append(float(parts[base + 2]))
        atoms.append({"shift": shift, "j_values": j_values})

    groups: dict[float, list[dict]] = defaultdict(list)
    for a in atoms:
        groups[a["shift"]].append(a)

    peaks = []
    for shift, group in sorted(groups.items(), reverse=True):
        n_h = len(group)
        j_values = group[0]["j_values"]

        if not j_values:
            mult = "s"
        else:
            rounded = sorted(set(round(j, 1) for j in j_values), reverse=True)
            if len(rounded) == 1:
                n_coupled = len(j_values)
                mult = _MULT.get(n_coupled, "m")
                rounded_str = f"{rounded[0]} Hz"
            else:
                mult = "m"
                rounded_str = ", ".join(f"{j} Hz" for j in rounded)
            mult = f"{mult} (J = {rounded_str})"

        peaks.append({"shift": shift, "n_h": n_h, "mult": mult})

    return peaks


def _spectrum_to_base64(peaks: list[dict], label: str) -> str:
    """Render NMR spectrum to PNG and return as base64 data URI."""
    shifts = [p["shift"] for p in peaks]
    x_min = max(shifts) + 1.0
    x_max = min(shifts) - 1.0
    ppm = np.linspace(x_min, x_max, 8000)

    lw = 0.015
    spectrum = np.zeros_like(ppm)
    for p in peaks:
        spectrum += p["n_h"] * (lw**2 / ((ppm - p["shift"]) ** 2 + lw**2))

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(ppm, spectrum, color="black", linewidth=1.0)
    ax.fill_between(ppm, spectrum, alpha=0.15, color="steelblue")

    for p in peaks:
        ax.axvline(p["shift"], color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.text(
            p["shift"], max(spectrum) * 1.05,
            f"{p['shift']:.2f}\n({p['n_h']}H)",
            ha="center", va="bottom", fontsize=7, color="navy",
        )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("δ (ppm)", fontsize=11)
    ax.set_ylabel("Intensity (a.u.)", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"¹H NMR predicted — {label}", fontsize=13, y=1.02)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@tool
def predict_nmr(smiles: str) -> str:
    """Predict 1H NMR spectrum for a molecule and return a peak table with a spectrum image.

    Uses the NMRdb.org web service for chemical shift and coupling prediction.
    Returns a markdown table of peaks and an inline spectrum image (base64 PNG).

    Args:
        smiles: SMILES string of the molecule to predict NMR for.
    """
    s = (smiles or "").strip()
    if not s:
        return "Error: SMILES string is empty."

    try:
        raw = _fetch_1h(s)
    except requests.HTTPError as e:
        return f"Error: NMRdb.org API returned an error: {e}"
    except Exception as e:
        return f"Error fetching NMR prediction: {e}"

    try:
        peaks = _parse_1h(raw)
    except Exception as e:
        return f"Error parsing NMR response: {e}"

    if not peaks:
        return "No NMR peaks predicted for this molecule."

    lines = [
        f"**¹H NMR prediction** for `{s}`:",
        "",
        "| δ (ppm) | nH | Multiplicity |",
        "|---------|-----|--------------|",
    ]
    for p in peaks:
        lines.append(f"| {p['shift']:.2f} | {p['n_h']} | {p['mult']} |")

    try:
        data_uri = _spectrum_to_base64(peaks, s)
        with _image_lock:
            _image_store[s] = data_uri
    except Exception as e:
        lines.append(f"\n(Spectrum image unavailable: {e})")

    return "\n".join(lines)
