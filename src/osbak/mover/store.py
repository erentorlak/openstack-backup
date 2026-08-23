from __future__ import annotations

from typing import Any, Protocol


class ChunkStore(Protocol):
    def put(self, chunk_hash: str, data: bytes) -> None: ...

    def get(self, chunk_hash: str) -> bytes | None: ...

    def exists(self, chunk_hash: str) -> bool: ...


class S3ChunkStore:
    """boto3 tabanlı canlı T1 deposu. Birim test DIŞI (canlı ortam).

    S3 anahtarı: `chunk/<blake2b>`. Tek hata yakalama: ClientError — 404 yok
    anlamına gelir ve `get/exists` için None/False döner (dar, anlamlı).
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
        except ClientError:
            return None

    def exists(self, chunk_hash: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(
                Bucket=self._bucket, Key=self._key(chunk_hash)
            )
            return True
        except ClientError:
            return False
