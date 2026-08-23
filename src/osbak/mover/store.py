from __future__ import annotations

from typing import Any, Protocol


class ChunkStore(Protocol):
    def put(self, chunk_hash: str, data: bytes) -> None: ...

    def get(self, chunk_hash: str) -> bytes | None: ...

    def exists(self, chunk_hash: str) -> bool: ...


class S3ChunkStore:
    """Live boto3-backed T1 store; OUT of unit-test scope (live environment).

    S3 key: `chunk/<blake2b>`. Narrow error contract: only HTTP 404 means "missing"
    and yields None/False from get/exists; any other ClientError (403, 500, ...) is
    re-raised so permission failures or outages are never masked as absent chunks.
    """

    def __init__(self, bucket: str, client: Any) -> None:
        self._bucket = bucket
        self._client = client

    @staticmethod
    def _key(chunk_hash: str) -> str:
        return f"chunk/{chunk_hash}"

    def put(self, chunk_hash: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=self._key(chunk_hash), Body=data
        )

    def get(self, chunk_hash: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(
                Bucket=self._bucket, Key=self._key(chunk_hash)
            )
            return resp["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                return None
            raise

    def exists(self, chunk_hash: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(
                Bucket=self._bucket, Key=self._key(chunk_hash)
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                return False
            raise
