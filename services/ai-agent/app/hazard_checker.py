"""
Hazard checker for ChemCrow2.

Loads hazardous_chemicals.json and scans text for mentions of dangerous
substances: by English/Russian name, IUPAC name, CAS number, or SMILES string.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent / "data" / "hazardous_chemicals.json"

# Lazy-loaded indexes
_loaded: bool = False
_name_index: dict[str, dict[str, Any]] = {}   # lowercase name/cas → chem record
_smiles_index: dict[str, dict[str, Any]] = {}  # smiles string → chem record

# Minimum token length to avoid false positives on single letters / short abbrevs
_MIN_NAME_LEN = 4

# Common words that appear in chemical names but are NOT chemical identifiers
_STOPWORDS: frozenset[str] = frozenset({
    # Russian generic chemistry words
    "кислота", "кислоты", "кислоте", "кислоту",
    "спирт", "спирта", "спирте",
    "жидкость", "жидкости",
    "смесь", "смеси",
    "раствор", "растворе", "раствора",
    "натрия", "калия", "кальция", "магния", "бария", "цинка", "меди",
    "соль", "соли", "солей",
    "оксид", "оксида",
    "хлорид", "хлорида",
    "сульфат", "нитрат", "ацетат", "карбонат",
    "трава", "корень", "листья", "экстракт",
    "таблетки", "капсулы", "порошок",
    "синтетический", "медицинский", "технический",
    "основание", "камфорат", "тартрат", "малеат",
    # English generic words
    "acid", "base", "salt", "oxide", "chloride", "sulfate", "nitrate",
    "solution", "mixture", "extract", "powder", "liquid",
    "sodium", "potassium", "calcium", "magnesium", "barium", "zinc",
    "synthetic", "medical", "technical",
})


def _tokenize(name: str) -> list[str]:
    """Split name into individual searchable tokens, filtering stopwords."""
    tokens = re.split(r"[^a-zA-Zа-яёА-ЯЁ0-9\-]", name)
    return [
        t.lower() for t in tokens
        if len(t) >= _MIN_NAME_LEN and t.lower() not in _STOPWORDS
    ]


def _load() -> None:
    global _loaded, _name_index, _smiles_index
    if _loaded:
        return

    chemicals: list[dict[str, Any]] = json.loads(
        _DB_PATH.read_text(encoding="utf-8")
    )

    for chem in chemicals:
        is_combo = chem.get("is_combination", False)

        for name in chem.get("names", []):
            if not name:
                continue
            _name_index[name.lower()] = chem
            # Для смесей/комбинаций НЕ индексируем отдельные токены —
            # иначе "methanol" из "methanol + ethylene glycol mixture"
            # будет ложно срабатывать на любое упоминание метанола.
            # Смесь показывается только если в тексте есть её полное название.
            if not is_combo:
                for token in _tokenize(name):
                    _name_index[token] = chem

        iupac = chem.get("iupac", "")
        if iupac and len(iupac) >= _MIN_NAME_LEN:
            _name_index[iupac.lower()] = chem

        cas = chem.get("cas", "")
        if cas:
            _name_index[cas] = chem

        smiles = chem.get("smiles", "")
        if smiles and len(smiles) >= 4:
            _smiles_index[smiles] = chem

    _loaded = True


def _safe_record(chem: dict[str, Any]) -> dict[str, Any]:
    """Return only fields the UI needs (keeps payload small)."""
    return {
        "id": chem.get("id", ""),
        "names": chem.get("names", [])[:2],
        "iupac": chem.get("iupac", ""),
        "cas": chem.get("cas", ""),
        "severity": chem.get("severity", "high"),
        "hazard_categories": chem.get("hazard_categories", []),
        "safety_warnings": chem.get("safety_warnings", [])[:5],
        "pkkn_list": chem.get("pkkn_list", ""),
        "description": chem.get("description", ""),
    }


# Regex to find SMILES-like strings in text (sequence of SMILES chars inside
# code spans, code blocks, or bare sequences without spaces)
_SMILES_PATTERN = re.compile(
    r"(?:```[\w]*\n([^`]+)```|`([^`\n]+)`|(?<!\w)([A-Za-z0-9@+\-\[\]()=#$./\\%:]{6,})(?!\w))"
)


def find_hazards(text: str) -> list[dict[str, Any]]:
    """
    Scan text for mentions of hazardous chemicals.

    Matches:
    - English names (substring, case-insensitive)
    - Russian names (substring, case-insensitive)
    - IUPAC names (substring, case-insensitive)
    - CAS numbers (exact match)
    - SMILES strings (exact match against known structures)

    Returns deduplicated list of UI-safe chemical records sorted by severity.
    """
    _load()

    found: dict[str, dict[str, Any]] = {}  # id → safe_record
    text_lower = text.lower()

    # ── Name / IUPAC / CAS matching ────────────────────────────────────────
    for pattern, chem in _name_index.items():
        if not pattern:
            continue
        if pattern in text_lower:
            chem_id = chem.get("id", "")
            if chem_id and chem_id not in found:
                found[chem_id] = _safe_record(chem)

    # ── SMILES matching — check extracted token candidates ──────────────────
    smiles_candidates: set[str] = set()
    for m in _SMILES_PATTERN.finditer(text):
        for g in m.groups():
            if g:
                # Split on whitespace/newlines if inside a code block
                for token in g.split():
                    token = token.strip(".,;:\"'")
                    if len(token) >= 4:
                        smiles_candidates.add(token)

    for candidate in smiles_candidates:
        chem = _smiles_index.get(candidate)
        if chem:
            chem_id = chem.get("id", "")
            if chem_id and chem_id not in found:
                found[chem_id] = _safe_record(chem)

    # Sort: critical first, then high
    severity_order = {"critical": 0, "high": 1, "medium": 2}
    return sorted(
        found.values(),
        key=lambda c: severity_order.get(c.get("severity", "high"), 1),
    )
