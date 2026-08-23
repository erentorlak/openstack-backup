from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from osbak.models import RestoreOp
from osbak.restore.gateway_mutations import RestoreGateway
from osbak.restore.model import RestorePlan, RestorePlanError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RebuildExecutor:
    def __init__(self, gateway: RestoreGateway, session: Session) -> None:
        self._gateway = gateway
        self._session = session

    def execute(self, op: RestoreOp, plan: RestorePlan) -> dict[str, Any]:
        # NOTE: this module does NOT create op — the service creates it as PLANNED (two-phase).
        # In-place mutation of the JSON column is not tracked (no MutableDict).
        # mapping is NOT written while EXECUTING (op.mapping stays {} from PLANNED); at the
        # end a NEW object (dict(mapping)) is assigned to op.mapping so SQLAlchemy sees the
        # change vs the PLANNED {}. Writing an empty-schema snapshot during EXECUTING would
        # have broken value-equality due to shared object references (M5 trap).
        mapping: dict[str, Any] = {"volumes": {}, "ports": {}, "security_groups": {}}
        op.state = "EXECUTING"
        self._session.commit()

        resolved: dict[str, str] = {}
        try:
            for step in sorted(plan.steps, key=lambda s: s.seq):
                payload = step.payload
                if step.action == "ensure_security_group_shell":
                    sid = self._gateway.ensure_security_group(
                        payload["name"], payload["description"], payload["project_id"]
                    )
                    resolved[step.key] = sid
                    mapping["security_groups"][payload["name"]] = sid
                elif step.action == "add_security_group_rules":
                    sg_key = payload["security_group_key"]
                    translated_rules = []
                    for rule in payload["rules"]:
                        r = dict(rule)
                        if "remote_group_name" in r:
                            r["remote_group_id"] = mapping["security_groups"][
                                r.pop("remote_group_name")
                            ]
                        translated_rules.append(r)
                    self._gateway.add_security_group_rules(resolved[sg_key], translated_rules)
                elif step.action == "create_volume":
                    vid = self._gateway.create_volume(
                        payload["name"], payload["size_gb"], payload["volume_type"],
                        payload["availability_zone"], None,
                    )
                    resolved[step.key] = vid
                    mapping["volumes"][step.key.split(":", 1)[1]] = vid
                elif step.action == "create_port":
                    sgs = [mapping["security_groups"][name] for name in payload["security_group_names"]]
                    pid = self._gateway.create_port(
                        payload["network_id"], payload["mac_address"], payload["fixed_ip"],
                        sgs, payload["allowed_address_pairs"], payload["project_id"],
                    )
                    resolved[step.key] = pid
                    mapping["ports"][step.key.split(":", 1)[1]] = pid
                elif step.action == "find_or_create_flavor":
                    fid = self._gateway.find_or_create_flavor(
                        payload["name"], payload["vcpus"], payload["ram_mb"],
                        payload["disk_gb"], payload["ephemeral_gb"], payload["swap_mb"],
                        payload["extra_specs"],
                    )
                    resolved[step.key] = fid
                    mapping["flavor"] = fid
                elif step.action == "create_server":
                    volume_ids = [resolved[k] for k in payload["volume_keys"]]
                    port_ids = [resolved[k] for k in payload["port_keys"]]
                    sgs = [mapping["security_groups"][name] for name in payload["security_group_names"]]
                    sid = self._gateway.create_server(
                        payload["name"], resolved[payload["flavor_key"]], volume_ids,
                        port_ids, sgs, payload["availability_zone"], payload["user_data"],
                        payload["key_name"], payload["metadata"], payload["tags"],
                        payload["config_drive"], payload["project_id"],
                    )
                    resolved[step.key] = sid
                    mapping["server"] = sid
                else:
                    raise RestorePlanError(f"bilinmeyen adim: {step.action}")
        except Exception as exc:  # noqa: BLE001 - teardown+re-raise (AGENTS izinli kalip)
            op.mapping = dict(mapping)
            op.state = "FAILED"
            op.error = str(exc)
            op.finished_at = _utcnow()
            self._session.commit()
            raise RestorePlanError(str(exc)) from exc

        op.mapping = dict(mapping)
        op.state = "DONE"
        op.finished_at = _utcnow()
        self._session.commit()
        return mapping
