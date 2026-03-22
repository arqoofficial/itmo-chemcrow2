import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.parser import detect_language, make_windows, make_bm25_chunk, Window


def test_make_windows_basic():
    windows = make_windows("abcdefghij", window_size=6, overlap=2)
    assert len(windows) == 2
    assert windows[0].text == "abcdef"
    assert windows[1].text == "efghij"


def test_make_windows_single_chunk():
    windows = make_windows("short", window_size=100, overlap=10)
    assert len(windows) == 1
    assert windows[0].text == "short"


def test_make_windows_empty():
    assert make_windows("") == []


def test_detect_language_english():
    text = "Chemistry is the scientific study of matter. " * 20
    assert detect_language(text) == "en"


def test_make_bm25_chunk_no_markdown():
    result = make_bm25_chunk("## Synthesis\n\nNaCl reacts.", lang="en")
    assert "##" not in result
    assert "NaCl" in result


async def test_process_pdf_uploads_conversation_scoped_chunks():
    """Chunk files must be uploaded under {conversation_id}/{doc_key}/."""
    from app.parser import process_pdf_to_minio

    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value="cleaned text")
    mock_minio = MagicMock()
    mock_minio.upload_chunk = MagicMock(return_value="parsed-chunks/conv-1/10_1234_test/_chunks/chunk_000.md")
    raw_md = "Word " * 2000  # long enough to produce multiple windows

    with patch("app.parser.asyncio.to_thread", new_callable=AsyncMock, return_value=raw_md), \
         patch("app.parser.build_chain", return_value=mock_chain):
        artifacts = await process_pdf_to_minio(
            b"%PDF fake",
            "job-001",
            "conv-1",
            "10_1234_test",
            mock_minio,
            MagicMock(),
        )

    assert mock_chain.ainvoke.call_count >= 1
    # upload_chunk must have been called with the conversation_id and doc_key
    calls = mock_minio.upload_chunk.call_args_list
    assert any(c.args[0] == "conv-1" and c.args[1] == "10_1234_test" for c in calls)
    assert "chunk_000" in artifacts
    assert "bm25_000" in artifacts
