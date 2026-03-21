import io
import pytest
from unittest.mock import MagicMock, patch, call


def test_upload_pdf_calls_put_object():
    mock_client = MagicMock()
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        client.upload_pdf("job123.pdf", b"%PDF-1.4 test content")
        mock_client.put_object.assert_called_once_with(
            Bucket="articles",
            Key="job123.pdf",
            Body=b"%PDF-1.4 test content",
            ContentType="application/pdf",
        )


def test_presign_url_calls_generate_presigned_url():
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "http://localhost:9000/articles/job123.pdf?sig=abc"
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        url = client.presign_url("job123.pdf", expires_in=3600)
        assert "job123.pdf" in url
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "articles", "Key": "job123.pdf"},
            ExpiresIn=3600,
        )


def test_ensure_bucket_creates_if_missing():
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = Exception("NoSuchBucket")
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        client.ensure_bucket()
        mock_client.create_bucket.assert_called_once_with(Bucket="articles")
