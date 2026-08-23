from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from osbak.discovery.gateway import OpenstackGateway, parse_host
from osbak.models import Instance, Project, VolumeRef, _utcnow


@dataclass(frozen=True)
class DiscoveryResult:
    projects: int = 0
    instances: int = 0
    volumes: int = 0


class DiscoveryService:
    def __init__(self, gateway: OpenstackGateway) -> None:
        self._gateway = gateway

    def refresh(self, session: Session, project_ids: list[str] | None = None) -> DiscoveryResult:
        result = DiscoveryResult()
        projects = self._gateway.list_projects()
        for info in projects:
            if project_ids is not None and info.id not in project_ids:
                continue
            project = self._get_or_create_project(session, info)
            result = DiscoveryResult(
                projects=result.projects + 1,
                instances=result.instances,
                volumes=result.volumes,
            )
            volumes = self._gateway.list_volumes(info.id)
            by_server: dict[str, list[str]] = {}
            volume_by_id = {v.id: v for v in volumes}
            for volume in volumes:
                for att in volume.attachments:
                    by_server.setdefault(att.server_id, []).append(volume.id)
            for server in self._gateway.list_servers(info.id):
                instance = self._get_or_create_instance(session, project, server)
                result = DiscoveryResult(
                    projects=result.projects,
                    instances=result.instances + 1,
                    volumes=result.volumes,
                )
                for volume_id in by_server.get(server.id, []):
                    volume = volume_by_id[volume_id]
                    self._get_or_create_volume_ref(session, instance, volume)
                    result = DiscoveryResult(
                        projects=result.projects,
                        instances=result.instances,
                        volumes=result.volumes + 1,
                    )
        session.commit()
        return result

    def _get_or_create_project(self, session: Session, info) -> Project:
        row = session.scalar(select(Project).where(Project.keystone_project_id == info.id))
        if row is None:
            row = Project(keystone_project_id=info.id, enabled=info.enabled)
            session.add(row)
            session.flush()
        return row

    def _get_or_create_instance(self, session: Session, project: Project, server) -> Instance:
        row = session.scalar(select(Instance).where(Instance.instance_uuid == server.id))
        if row is None:
            row = Instance(instance_uuid=server.id, project_id=project.id)
            session.add(row)
            session.flush()
        else:
            row.last_seen_at = _utcnow()
        return row

    def _get_or_create_volume_ref(self, session: Session, instance: Instance, info) -> VolumeRef:
        row = session.scalar(
            select(VolumeRef).where(
                VolumeRef.instance_id == instance.id,
                VolumeRef.volume_uuid == info.id,
            )
        )
        host = parse_host(info.host)
        if row is None:
            row = VolumeRef(
                instance_id=instance.id,
                volume_uuid=info.id,
                boot_index=0 if info.bootable else -1,
                size_gb=info.size,
                volume_type=info.volume_type or None,
                backend=host.driver,
                pool=host.pool,
            )
            session.add(row)
            session.flush()
        else:
            row.boot_index = 0 if info.bootable else -1
            row.size_gb = info.size
            row.volume_type = info.volume_type or None
            row.backend = host.driver
            row.pool = host.pool
        return row
