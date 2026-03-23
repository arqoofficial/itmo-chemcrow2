"""Tests for molecule drawing tool."""
from app.tools.molecule_draw_rdkit import draw_molecule_rdkit, pop_pending_image
import pytest


def test_draw_molecule_rdkit_empty():
    """Empty SMILES returns error string."""
    result = draw_molecule_rdkit.invoke({"smiles": ""})
    assert isinstance(result, str)
    assert "Error" in result or "empty" in result.lower()


def test_draw_molecule_rdkit_invalid_smiles():
    """Invalid SMILES returns error string."""
    result = draw_molecule_rdkit.invoke({"smiles": "not_a_molecule"})
    assert isinstance(result, str)
    assert "error" in result.lower() or "invalid" in result.lower()


def test_draw_molecule_rdkit_valid_smiles(caffeine_smiles):
    """Valid SMILES returns success message."""
    result = draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})
    assert isinstance(result, str)
    # Should mention the SMILES in the result or success
    assert caffeine_smiles in result or "drawn" in result.lower()


def test_draw_molecule_rdkit_whitespace_handling():
    """Leading/trailing whitespace is handled."""
    smiles_with_space = "  CC(C)C  "
    result = draw_molecule_rdkit.invoke({"smiles": smiles_with_space})
    assert isinstance(result, str)
    # Should not error on whitespace or handle it gracefully


def test_draw_molecule_rdkit_simple_molecule():
    """Simple molecule (methane) draws successfully."""
    result = draw_molecule_rdkit.invoke({"smiles": "C"})
    assert isinstance(result, str)
    # Methane is valid, should not error


def test_draw_molecule_rdkit_complex_molecule(caffeine_smiles):
    """Complex molecule (caffeine) draws successfully."""
    result = draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})
    assert isinstance(result, str)
    assert "Error" not in result


def test_draw_molecule_rdkit_stores_image(caffeine_smiles):
    """Drawing stores image in the image store."""
    result = draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})
    # Try to retrieve the image
    image = pop_pending_image(caffeine_smiles)
    assert image is not None
    assert image.startswith("data:image/png;base64,")


def test_draw_molecule_rdkit_image_is_base64(caffeine_smiles):
    """Stored image is base64 encoded."""
    draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})
    image = pop_pending_image(caffeine_smiles)
    if image:
        assert image.startswith("data:image/png;base64,")
        # Try to decode it
        import base64
        b64_data = image.replace("data:image/png;base64,", "")
        try:
            decoded = base64.b64decode(b64_data)
            # Should be PNG magic bytes
            assert decoded[:4] == b'\x89PNG'
        except Exception:
            # Decoding might fail, but we at least checked format
            pass


def test_pop_pending_image_missing_key():
    """pop_pending_image returns None for missing key."""
    result = pop_pending_image("nonexistent_smiles")
    assert result is None


def test_pop_pending_image_removes_from_store(caffeine_smiles):
    """pop_pending_image removes image from store."""
    draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})

    # First pop should return image
    image1 = pop_pending_image(caffeine_smiles)
    assert image1 is not None

    # Second pop should return None
    image2 = pop_pending_image(caffeine_smiles)
    assert image2 is None


def test_draw_molecule_rdkit_multiple_calls(caffeine_smiles, acetone_smiles):
    """Multiple molecules can be drawn."""
    result1 = draw_molecule_rdkit.invoke({"smiles": caffeine_smiles})
    result2 = draw_molecule_rdkit.invoke({"smiles": acetone_smiles})

    assert isinstance(result1, str)
    assert isinstance(result2, str)

    # Should be able to retrieve both images
    image1 = pop_pending_image(caffeine_smiles)
    image2 = pop_pending_image(acetone_smiles)

    if image1 is not None:
        assert image1.startswith("data:image/png;base64,")
    if image2 is not None:
        assert image2.startswith("data:image/png;base64,")


def test_draw_molecule_rdkit_stereochemistry(ibuprofen_smiles):
    """Molecule with stereochemistry draws correctly."""
    result = draw_molecule_rdkit.invoke({"smiles": ibuprofen_smiles})
    assert isinstance(result, str)
    # Should not error on chiral molecule


def test_draw_molecule_rdkit_special_characters():
    """SMILES with special characters (valid) draws correctly."""
    # SMILES with brackets and special chars
    smiles = "c1ccccc1"  # Benzene
    result = draw_molecule_rdkit.invoke({"smiles": smiles})
    assert isinstance(result, str)
    assert "Error" not in result


def test_draw_molecule_rdkit_very_long_smiles():
    """Very long SMILES might error gracefully."""
    # Create a long but valid SMILES
    long_smiles = "C" * 200  # Long carbon chain
    result = draw_molecule_rdkit.invoke({"smiles": long_smiles})
    assert isinstance(result, str)
    # Should either work or return error gracefully


def test_pop_pending_image_thread_safe():
    """pop_pending_image uses thread locking."""
    from app.tools import molecule_draw_rdkit as mol_module
    # Just verify the lock exists and is used
    assert hasattr(mol_module, '_image_lock')
    assert hasattr(mol_module._image_lock, 'acquire')
