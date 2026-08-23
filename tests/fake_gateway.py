from __future__ import annotations

from osbak.discovery.gateway import (
    FlavorInfo,
    OpenstackGateway,
    PortInfo,
    ProjectInfo,
    SecurityGroupInfo,
    ServerGroupInfo,
    ServerInfo,
    VolumeInfo,
)


class FakeGateway(OpenstackGateway):
    def __init__(
        self,
        projects: list[ProjectInfo] | None = None,
        servers: dict[str, list[ServerInfo]] | None = None,
        volumes: dict[str, list[VolumeInfo]] | None = None,
        ports: dict[str, list[PortInfo]] | None = None,
        security_groups: dict[str, list[SecurityGroupInfo]] | None = None,
        server_groups: dict[str, list[ServerGroupInfo]] | None = None,
        flavors: dict[str, FlavorInfo] | None = None,
    ) -> None:
        self._projects = projects or []
        self._servers = servers or {}
        self._volumes = volumes or {}
        self._ports = ports or {}
        self._security_groups = security_groups or {}
        self._server_groups = server_groups or {}
        self._flavors = flavors or {}
        self._quiesced: list[str] = []
        self._unquiesced: list[str] = []

    def list_projects(self) -> list[ProjectInfo]:
        return list(self._projects)

    def list_servers(self, project_id: str) -> list[ServerInfo]:
        return list(self._servers.get(project_id, []))

    def list_volumes(self, project_id: str) -> list[VolumeInfo]:
        return list(self._volumes.get(project_id, []))

    def list_ports(self, project_id: str, device_id: str | None = None) -> list[PortInfo]:
        if device_id is None:
            return list(self._ports.get(project_id, []))
        return [p for p in self._ports.get(project_id, []) if p.device_id == device_id]

    def list_security_groups(self, project_id: str) -> list[SecurityGroupInfo]:
        return list(self._security_groups.get(project_id, []))

    def list_server_groups(self, project_id: str) -> list[ServerGroupInfo]:
        return list(self._server_groups.get(project_id, []))

    def list_flavors(self) -> dict[str, FlavorInfo]:
        return dict(self._flavors)

    def get_flavor(self, flavor_id: str) -> FlavorInfo | None:
        return self._flavors.get(flavor_id)

    def quiesce_guest(self, server_id: str) -> None:
        self._quiesced.append(server_id)

    def unquiesce_guest(self, server_id: str) -> None:
        self._unquiesced.append(server_id)
