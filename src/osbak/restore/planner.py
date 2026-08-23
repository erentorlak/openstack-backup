from __future__ import annotations

from typing import Any

from osbak.restore.model import (
    PlanStep,
    RestoreOptions,
    RestorePlan,
    RestorePlanError,
    RestoreStrategy,
)


class RestorePlanner:
    def __init__(self, manifest: dict, options: RestoreOptions, restore_point_id: int) -> None:
        if options.strategy is not RestoreStrategy.REBUILD:
            raise RestorePlanError("henüz desteklenmiyor")
        self._manifest = manifest
        self._options = options
        self._restore_point_id = restore_point_id

    def build(self) -> RestorePlan:
        manifest = self._manifest
        steps: list[PlanStep] = []
        seq = 0

        sg_id_to_name = {sg["id"]: sg["name"] for sg in manifest["security_groups"]}

        for sg in manifest["security_groups"]:
            steps.append(PlanStep(
                seq=seq, action="ensure_security_group_shell",
                key=f"sg:{sg['name']}",
                payload={"name": sg["name"], "description": sg["description"],
                         "project_id": manifest["project_id"]},
            ))
            seq += 1

        for sg in manifest["security_groups"]:
            translated_rules = []
            for rule in sg["rules"]:
                r = dict(rule)
                rgid = r.get("remote_group_id")
                if rgid:
                    name = sg_id_to_name.get(rgid)
                    if name is None:
                        raise RestorePlanError(f"bilinmeyen uzak grup: {rgid}")
                    del r["remote_group_id"]
                    r["remote_group_name"] = name
                translated_rules.append(r)
            steps.append(PlanStep(
                seq=seq, action="add_security_group_rules",
                key=f"sg_rules:{sg['name']}",
                payload={"security_group_key": f"sg:{sg['name']}", "rules": translated_rules},
            ))
            seq += 1

        for bdm in sorted(manifest["block_device_mapping"], key=lambda b: b["boot_index"]):
            steps.append(PlanStep(
                seq=seq, action="create_volume",
                key=f"vol:{bdm['volume_id']}",
                payload={"name": f"restored-{bdm['volume_id']}",
                         "size_gb": bdm["size"],
                         "volume_type": bdm["volume_type"] or None,
                         "availability_zone": self._options.availability_zone},
            ))
            seq += 1

        ports = manifest["network"]["ports"]
        for i, port in enumerate(ports):
            fixed_ip = None
            if self._options.keep_ip and port["fixed_ips"]:
                fixed_ip = port["fixed_ips"][0]["ip_address"]
            steps.append(PlanStep(
                seq=seq, action="create_port",
                key=f"port:{port['id']}",
                payload={"network_id": port["network_id"],
                         "mac_address": port["mac_address"],
                         "fixed_ip": fixed_ip,
                         "security_group_names": [
                             sg_id_to_name[sid] for sid in port["security_group_ids"]
                             if sid in sg_id_to_name
                         ],
                         "allowed_address_pairs": port["allowed_address_pairs"],
                         "project_id": manifest["project_id"]},
            ))
            seq += 1

        flavor = manifest["flavor"]
        if flavor is None:
            raise RestorePlanError("flavor bilgisi eksik")
        steps.append(PlanStep(
            seq=seq, action="find_or_create_flavor", key="flavor",
            payload={"name": flavor["name"], "vcpus": flavor["vcpus"],
                     "ram_mb": flavor["ram"], "disk_gb": flavor["disk"],
                     "ephemeral_gb": flavor["ephemeral"], "swap_mb": flavor["swap"],
                     "extra_specs": flavor.get("extra_specs", {})},
        ))
        seq += 1

        instance = manifest["instance"]
        steps.append(PlanStep(
            seq=seq, action="create_server", key="server",
            payload={
                "name": self._options.instance_name or instance["name"],
                "flavor_key": "flavor",
                "volume_keys": [f"vol:{b['volume_id']}"
                                for b in sorted(manifest["block_device_mapping"], key=lambda b: b["boot_index"])],
                "port_keys": [f"port:{p['id']}" for p in ports],
                "security_group_names": [sg["name"] for sg in manifest["security_groups"]],
                "availability_zone": self._options.availability_zone or instance.get("availability_zone"),
                "user_data": None,
                "key_name": instance.get("key_name"),
                "metadata": instance.get("metadata", {}),
                "tags": instance.get("tags", []),
                "config_drive": instance.get("config_drive", False),
                "project_id": instance["project_id"],
            },
        ))
        seq += 1

        return RestorePlan(
            strategy=RestoreStrategy.REBUILD,
            restore_point_id=self._restore_point_id,
            steps=tuple(steps),
            resource_delta={
                "volumes": len(manifest["block_device_mapping"]),
                "ports": len(ports),
                "security_groups": len(manifest["security_groups"]),
                "flavors": 1,
                "servers": 1,
            },
        )
