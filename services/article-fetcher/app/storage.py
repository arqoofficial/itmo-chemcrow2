import logging
import boto3
from botocore.client import Config

logger = logging.getLogger(__name__)


class StorageClient:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_endpoint: str,
    ):
        self._bucket = bucket
        self._public_endpoint = public_endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            logger.warning("Bucket %s not found, creating", self._bucket)
            self._client.create_bucket(Bucket=self._bucket)

    def upload_pdf(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )
        logger.info("Uploaded %s to bucket %s", key, self._bucket)

    def presign_url(self, key: str, expires_in: int = 3600) -> str:
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        # Rewrite internal endpoint to public endpoint for external access
        if self._public_endpoint and self._public_endpoint not in url:
            internal = self._client.meta.endpoint_url
            url = url.replace(internal, self._public_endpoint)
        return url
