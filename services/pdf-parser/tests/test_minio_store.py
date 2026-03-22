import io
import pytest
from unittest.mock import MagicMock
from app.minio_store import MinioStore


@pytest.fixture
def store():
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True
    return MinioStore(
        client=mock_client,
        input_bucket="articles",
        output_bucket="parsed-chunks",
    )


def test_download_pdf(store):
    mock_response = MagicMock()
    mock_response.read.return_value = b"%PDF content"
    store._client.get_object.return_value = mock_response
    result = store.download_pdf("abc123.pdf")
    assert result == b"%PDF content"
    store._client.get_object.assert_called_once_with("articles", "abc123.pdf")


def test_upload_chunk(store):
    store.upload_chunk("conv-1", "10_1234_test", "_chunks", "chunk_000.md", "# Hello")
    store._client.put_object.assert_called_once()
    call_args = store._client.put_object.call_args
    assert call_args[0][0] == "parsed-chunks"
    assert call_args[0][1] == "conv-1/10_1234_test/_chunks/chunk_000.md"


def test_upload_chunk_bm25(store):
    store.upload_chunk("conv-1", "10_1234_test", "_bm25_chunks", "chunk_000.txt", "clean text")
    call_args = store._client.put_object.call_args
    assert call_args[0][1] == "conv-1/10_1234_test/_bm25_chunks/chunk_000.txt"


def test_list_chunk_keys(store):
    obj1 = MagicMock()
    obj1.object_name = "conv-1/10_1234_test/_chunks/chunk_000.md"
    obj2 = MagicMock()
    obj2.object_name = "conv-1/10_1234_test/_bm25_chunks/chunk_000.txt"
    store._client.list_objects.return_value = [obj1, obj2]
    keys = store.list_chunk_keys("conv-1", "10_1234_test")
    assert "conv-1/10_1234_test/_chunks/chunk_000.md" in keys
    store._client.list_objects.assert_called_once_with(
        "parsed-chunks", prefix="conv-1/10_1234_test/", recursive=True
    )
