import io
import logging
from minio import Minio

log = logging.getLogger(__name__)


class MinioStore:
    def __init__(self, client: Minio, input_bucket: str, output_bucket: str):
        self._client = client
        self._input_bucket = input_bucket
        self._output_bucket = output_bucket

    def ensure_buckets(self) -> None:
        for bucket in (self._input_bucket, self._output_bucket):
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
                log.info("minio_store: created bucket %s", bucket)

    def download_pdf(self, object_key: str) -> bytes:
        """Download a PDF from the input bucket."""
        response = self._client.get_object(self._input_bucket, object_key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        log.info("minio_store: downloaded %s (%d bytes)", object_key, len(data))
        return data

    def upload_chunk(
        self,
        conversation_id: str,
        doc_key: str,
        chunk_dir: str,   # "_chunks" or "_bm25_chunks"
        filename: str,
        text: str,
        encoding: str = "utf-8",
    ) -> str:
        """Upload a single chunk file. Returns the object key."""
        object_key = f"{conversation_id}/{doc_key}/{chunk_dir}/{filename}"
        data = text.encode(encoding)
        self._client.put_object(
            self._output_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
        log.info("minio_store: uploaded chunk %s", object_key)
        return object_key

    def list_chunk_keys(self, conversation_id: str, doc_key: str) -> list[str]:
        """List all chunk object keys for a given conversation + doc."""
        prefix = f"{conversation_id}/{doc_key}/"
        objects = self._client.list_objects(self._output_bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]


def make_minio_store(
    endpoint: str,
    access_key: str,
    secret_key: str,
    input_bucket: str,
    output_bucket: str,
    secure: bool = False,
) -> MinioStore:
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    store = MinioStore(client=client, input_bucket=input_bucket, output_bucket=output_bucket)
    store.ensure_buckets()
    return store
