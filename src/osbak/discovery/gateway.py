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
