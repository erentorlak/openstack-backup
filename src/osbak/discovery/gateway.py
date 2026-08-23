from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class HostInfo:
    host: str
    driver: str | None = None
    pool: str | None = None


def parse_host(host: str) -> HostInfo:
    node, sep1, rest = host.partition("@")
    if not sep1:
        return HostInfo(host=node)
    driver, sep2, pool = rest.partition("#")
    return HostInfo(host=node, driver=driver, pool=pool if sep2 else None)


@dataclass(frozen=True)
class ProjectInfo:
    id: str
    name: str
    domain_id: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class VolumeAttachment:
    server_id: str
    device: str | None
    attachment_id: str | None
    volume_id: str


@dataclass(frozen=True)
class VolumeInfo:
    id: str
    name: str
    size: int
    volume_type: str
    status: str
    bootable: bool
    host: str
    project_id: str | None = None
    attachments: tuple[VolumeAttachment, ...] = ()
    created_at: str | None = None


@dataclass(frozen=True)
class FlavorInfo:
    id: str
    name: str
    vcpus: int
    ram: int
    disk: int
    ephemeral: int
    swap: int
    is_public: bool
    extra_specs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServerInfo:
    id: str
    name: str
    project_id: str
    status: str
    flavor_id: str
    key_name: str | None = None
    config_drive: bool = False
    availability_zone: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    addresses: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PortInfo:
    id: str
    network_id: str
    mac_address: str
    device_id: str | None = None
    fixed_ips: tuple[dict[str, Any], ...] = ()
    security_group_ids: tuple[str, ...] = ()
    allowed_address_pairs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SecurityGroupRule:
    id: str
    direction: str | None = None
    protocol: str | None = None
    ether_type: str | None = None
    port_range_min: int | None = None
    port_range_max: int | None = None
    remote_ip_prefix: str | None = None
    remote_group_id: str | None = None


@dataclass(frozen=True)
class SecurityGroupInfo:
    id: str
    name: str
    description: str = ""
    project_id: str | None = None
    rules: tuple[SecurityGroupRule, ...] = ()


@dataclass(frozen=True)
class ServerGroupInfo:
    id: str
    name: str
    project_id: str | None = None
    policies: tuple[str, ...] = ()
    member_ids: tuple[str, ...] = ()


class OpenstackGateway(Protocol):
    def list_projects(self) -> list[ProjectInfo]: ...
    def list_servers(self, project_id: str) -> list[ServerInfo]: ...
    def list_volumes(self, project_id: str) -> list[VolumeInfo]: ...
    def list_ports(self, project_id: str, device_id: str | None = None) -> list[PortInfo]: ...
    def list_security_groups(self, project_id: str) -> list[SecurityGroupInfo]: ...
    def list_server_groups(self, project_id: str) -> list[ServerGroupInfo]: ...
    def list_flavors(self) -> dict[str, FlavorInfo]: ...
    def get_flavor(self, flavor_id: str) -> FlavorInfo | None: ...


def project_from_dict(d: dict[str, Any]) -> ProjectInfo:
    return ProjectInfo(id=d["id"], name=d.get("name") or "", enabled=d.get("is_enabled", True))


def volume_from_dict(d: dict[str, Any]) -> VolumeInfo:
    attachments = tuple(
        VolumeAttachment(
            server_id=a["server_id"],
            device=a.get("device"),
            attachment_id=a.get("attachment_id"),
            volume_id=a.get("volume_id", a.get("id", "")),
        )
        for a in d.get("attachments") or []
    )
    return VolumeInfo(
        id=d["id"],
        name=d.get("name") or "",
        size=int(d.get("size") or 0),
        volume_type=d.get("volume_type") or "",
        status=d.get("status") or "",
        bootable=str(d.get("bootable", "false")).lower() == "true",
        host=d.get("host") or "",
        project_id=d.get("project_id"),
        attachments=attachments,
        created_at=d.get("created_at"),
    )


def server_from_dict(d: dict[str, Any]) -> ServerInfo:
    flavor = d.get("flavor") or {}
    return ServerInfo(
        id=d["id"],
        name=d.get("name") or "",
        project_id=d.get("project_id") or "",
        status=d.get("status") or "",
        flavor_id=flavor.get("id") or "",
        key_name=d.get("key_name"),
        config_drive=bool(d.get("config_drive", False)),
        availability_zone=d.get("availability_zone"),
        created_at=d.get("created_at"),
        metadata=dict(d.get("metadata") or {}),
        tags=tuple(d.get("tags") or ()),
        addresses=dict(d.get("addresses") or {}),
    )


def port_from_dict(d: dict[str, Any]) -> PortInfo:
    return PortInfo(
        id=d["id"],
        network_id=d.get("network_id") or "",
        mac_address=d.get("mac_address") or "",
        device_id=d.get("device_id"),
        fixed_ips=tuple(d.get("fixed_ips") or ()),
        security_group_ids=tuple(d.get("security_group_ids") or ()),
        allowed_address_pairs=tuple(d.get("allowed_address_pairs") or ()),
    )


def flavor_from_dict(d: dict[str, Any]) -> FlavorInfo:
    return FlavorInfo(
        id=d["id"],
        name=d.get("name") or "",
        vcpus=int(d.get("vcpus") or 0),
        ram=int(d.get("ram") or 0),
        disk=int(d.get("disk") or 0),
        ephemeral=int(d.get("ephemeral") or 0),
        swap=int(d.get("swap") or 0),
        is_public=bool(d.get("is_public", True)),
        extra_specs=dict(d.get("extra_specs") or {}),
    )


def security_group_from_dict(d: dict[str, Any]) -> SecurityGroupInfo:
    rules = tuple(
        SecurityGroupRule(
            id=r.get("id") or "",
            direction=r.get("direction"),
            protocol=r.get("protocol"),
            ether_type=r.get("ether_type"),
            port_range_min=r.get("port_range_min"),
            port_range_max=r.get("port_range_max"),
            remote_ip_prefix=r.get("remote_ip_prefix"),
            remote_group_id=r.get("remote_group_id"),
        )
        for r in d.get("security_group_rules") or ()
    )
    return SecurityGroupInfo(
        id=d["id"],
        name=d.get("name") or "",
        description=d.get("description") or "",
        project_id=d.get("project_id"),
        rules=rules,
    )


def server_group_from_dict(d: dict[str, Any]) -> ServerGroupInfo:
    return ServerGroupInfo(
        id=d["id"],
        name=d.get("name") or "",
        project_id=d.get("project_id"),
        policies=tuple(d.get("policies") or ()),
        member_ids=tuple(d.get("member_ids") or ()),
    )


class SDKGateway:
    """openstacksdk bağlantısını saran gerçek implementasyon (canlı ortamda çalışır).

    Birim test kapsamı DIŞI: onun yerine saf *_from_dict fonksiyonları test edilir.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def list_projects(self) -> list[ProjectInfo]:
        return [project_from_dict(p.to_dict()) for p in self._conn.list_projects()]

    def list_servers(self, project_id: str) -> list[ServerInfo]:
        raw = self._conn.compute.servers(all_projects=True, project_id=project_id)
        return [server_from_dict(s.to_dict()) for s in raw]

    def list_volumes(self, project_id: str) -> list[VolumeInfo]:
        raw = self._conn.block_storage.volumes(all_projects=True, project_id=project_id)
        return [volume_from_dict(v.to_dict()) for v in raw]

    def list_ports(self, project_id: str, device_id: str | None = None) -> list[PortInfo]:
        query: dict[str, Any] = {"project_id": project_id}
        if device_id is not None:
            query["device_id"] = device_id
        return [port_from_dict(p.to_dict()) for p in self._conn.network.ports(**query)]

    def list_security_groups(self, project_id: str) -> list[SecurityGroupInfo]:
        raw = self._conn.network.security_groups(project_id=project_id)
        return [security_group_from_dict(x.to_dict()) for x in raw]

    def list_server_groups(self, project_id: str) -> list[ServerGroupInfo]:
        raw = self._conn.compute.server_groups(all_projects=True)
        return [server_group_from_dict(x.to_dict()) for x in raw if x.project_id == project_id]

    def list_flavors(self) -> dict[str, FlavorInfo]:
        raw = self._conn.compute.flavors(details=True, get_extra_specs=True)
        return {f.id: flavor_from_dict(f.to_dict()) for f in raw if f.id}

    def get_flavor(self, flavor_id: str) -> FlavorInfo | None:
        flavor = self._conn.compute.find_flavor(flavor_id, get_extra_specs=True)
        return None if flavor is None else flavor_from_dict(flavor.to_dict())
