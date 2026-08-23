from __future__ import annotations

from datetime import datetime, timezone

from osbak.discovery.gateway import OpenstackGateway, ServerInfo, parse_host


class ManifestBuilder:
    def __init__(self, gateway: OpenstackGateway) -> None:
        self._gateway = gateway

    def build(self, project_id: str, server: ServerInfo) -> dict:
        flavor = self._gateway.get_flavor(server.flavor_id)
        ports = self._gateway.list_ports(project_id, device_id=server.id)
        volumes = [
            volume
            for volume in self._gateway.list_volumes(project_id)
            if any(a.server_id == server.id for a in volume.attachments)
        ]
        wanted_sg_ids = {sg for port in ports for sg in port.security_group_ids}
        security_groups = [
            group
            for group in self._gateway.list_security_groups(project_id)
            if group.id in wanted_sg_ids
        ]
        server_groups = [
            group
            for group in self._gateway.list_server_groups(project_id)
            if server.id in group.member_ids
        ]
        return {
            "schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "instance": {
                "id": server.id,
                "name": server.name,
                "project_id": server.project_id,
                "status": server.status,
                "flavor_id": server.flavor_id,
                "key_name": server.key_name,
                "config_drive": server.config_drive,
                "availability_zone": server.availability_zone,
                "created_at": server.created_at,
                "metadata": dict(server.metadata),
                "tags": list(server.tags),
                "addresses": dict(server.addresses),
            },
            "flavor": None if flavor is None else {
                "id": flavor.id,
                "name": flavor.name,
                "vcpus": flavor.vcpus,
                "ram": flavor.ram,
                "disk": flavor.disk,
                "ephemeral": flavor.ephemeral,
                "swap": flavor.swap,
                "is_public": flavor.is_public,
                "extra_specs": dict(flavor.extra_specs),
            },
            "block_device_mapping": [self._volume_to_bdm(volume) for volume in volumes],
            "network": {"ports": [self._port_to_dict(port) for port in ports]},
            "security_groups": [self._security_group_to_dict(group) for group in security_groups],
            "server_groups": [
                {
                    "id": group.id,
                    "name": group.name,
                    "policies": list(group.policies),
                    "member_ids": list(group.member_ids),
                }
                for group in server_groups
            ],
        }

    def _volume_to_bdm(self, volume) -> dict:
        host = parse_host(volume.host)
        return {
            "volume_id": volume.id,
            "boot_index": 0 if volume.bootable else -1,
            "size": volume.size,
            "volume_type": volume.volume_type or "",
            "backend": host.driver or "",
            "pool": host.pool or "",
        }

    def _port_to_dict(self, port) -> dict:
        return {
            "id": port.id,
            "network_id": port.network_id,
            "mac_address": port.mac_address,
            "fixed_ips": [dict(f) for f in port.fixed_ips],
            "security_group_ids": list(port.security_group_ids),
            "allowed_address_pairs": [dict(a) for a in port.allowed_address_pairs],
        }

    def _security_group_to_dict(self, group) -> dict:
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "rules": [
                {
                    "id": rule.id,
                    "direction": rule.direction,
                    "protocol": rule.protocol,
                    "ether_type": rule.ether_type,
                    "port_range_min": rule.port_range_min,
                    "port_range_max": rule.port_range_max,
                    "remote_ip_prefix": rule.remote_ip_prefix,
                    "remote_group_id": rule.remote_group_id,
                }
                for rule in group.rules
            ],
        }
