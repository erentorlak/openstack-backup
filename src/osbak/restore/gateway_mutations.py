from __future__ import annotations

from typing import Any, Protocol


class RestoreGateway(Protocol):
    def ensure_security_group(
        self, name: str, description: str, project_id: str
    ) -> str: ...

    def add_security_group_rules(
        self, security_group_id: str, rules: list[dict]
    ) -> None: ...

    def create_volume(
        self,
        name: str,
        size_gb: int,
        volume_type: str | None,
        availability_zone: str | None,
        source_snapshot: str | None,
    ) -> str: ...

    def create_port(
        self,
        network_id: str,
        mac_address: str | None,
        fixed_ip: str | None,
        security_group_ids: list[str],
        allowed_address_pairs: list[dict],
        project_id: str,
    ) -> str: ...

    def find_or_create_flavor(
        self,
        name: str,
        vcpus: int,
        ram_mb: int,
        disk_gb: int,
        ephemeral_gb: int,
        swap_mb: int,
        extra_specs: dict,
    ) -> str: ...

    def create_server(
        self,
        name: str,
        flavor_id: str,
        volume_ids: list[str],
        port_ids: list[str],
        security_group_ids: list[str],
        availability_zone: str | None,
        user_data: str | None,
        key_name: str | None,
        metadata: dict,
        tags: list[str],
        config_drive: bool,
        project_id: str,
    ) -> str: ...


class SDKRestoreGateway:
    """Canlı mutasyon sarmalayıcı — birim test DIŞI (canlı ortam doğrulaması).

    Metotlar Nova/Neutron/Cinder'a delegate eder; tam API çağrıları
    canlı ortamda doğrulanacak. Sözleşme imzaları yukarıdaki Protocol ile aynıdır.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def ensure_security_group(self, name: str, description: str, project_id: str) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def add_security_group_rules(self, security_group_id: str, rules: list[dict]) -> None:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_volume(
        self, name: str, size_gb: int, volume_type: str | None,
        availability_zone: str | None, source_snapshot: str | None,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_port(
        self, network_id: str, mac_address: str | None, fixed_ip: str | None,
        security_group_ids: list[str], allowed_address_pairs: list[dict], project_id: str,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def find_or_create_flavor(
        self, name: str, vcpus: int, ram_mb: int, disk_gb: int,
        ephemeral_gb: int, swap_mb: int, extra_specs: dict,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_server(
        self, name: str, flavor_id: str, volume_ids: list[str], port_ids: list[str],
        security_group_ids: list[str], availability_zone: str | None,
        user_data: str | None, key_name: str | None, metadata: dict,
        tags: list[str], config_drive: bool, project_id: str,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")
