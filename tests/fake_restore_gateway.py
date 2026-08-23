from __future__ import annotations

from osbak.restore.gateway_mutations import RestoreGateway


class FakeRestoreGateway(RestoreGateway):
    def __init__(self) -> None:
        self.created: dict[str, list] = {}
        self._next_id = 0
        self._sg_ids: dict[str, str] = {}

    def _new_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def ensure_security_group(self, name, description, project_id):
        if name in self._sg_ids:
            return self._sg_ids[name]
        sg_id = self._new_id("sg")
        self._sg_ids[name] = sg_id
        self.created.setdefault("security_groups", []).append({"id": sg_id, "name": name})
        return sg_id

    def add_security_group_rules(self, security_group_id, rules):
        self.created.setdefault("sg_rules", []).append({"id": security_group_id, "rules": rules})

    def create_volume(self, name, size_gb, volume_type, availability_zone, source_snapshot):
        vid = self._new_id("vol")
        self.created.setdefault("volumes", []).append(
            {"id": vid, "name": name, "size": size_gb, "type": volume_type,
             "az": availability_zone, "source_snapshot": source_snapshot})
        return vid

    def create_port(self, network_id, mac_address, fixed_ip, security_group_ids,
                    allowed_address_pairs, project_id):
        pid = self._new_id("port")
        self.created.setdefault("ports", []).append(
            {"id": pid, "network_id": network_id, "mac": mac_address, "fixed_ip": fixed_ip,
             "sgs": security_group_ids, "aap": allowed_address_pairs})
        return pid

    def find_or_create_flavor(self, name, vcpus, ram_mb, disk_gb, ephemeral_gb, swap_mb, extra_specs):
        fid = self._new_id("flavor")
        self.created.setdefault("flavors", []).append(
            {"id": fid, "name": name, "vcpus": vcpus, "ram": ram_mb, "disk": disk_gb})
        return fid

    def create_server(self, name, flavor_id, volume_ids, port_ids, security_group_ids,
                      availability_zone, user_data, key_name, metadata, tags,
                      config_drive, project_id):
        sid = self._new_id("server")
        self.created.setdefault("servers", []).append(
            {"id": sid, "name": name, "flavor": flavor_id, "volumes": volume_ids,
             "ports": port_ids, "sgs": security_group_ids, "az": availability_zone})
        return sid
