from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from osbak.discovery.gateway import OpenstackGateway, parse_host
from osbak.manifest.builder import ManifestBuilder
from osbak.models import Instance, RestorePoint, VolumeBackup, VolumeRef
from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import PlanKind, ValidationReport
from osbak.providers.base import ProviderUnavailable, SnapshotProvider, SnapshotRef, SnapshotTarget
from osbak.preflight.rules import instances, keystone  # noqa: F401  (register checks)


@dataclass(frozen=True)
class SnapshotOptions:
    require_consistent: bool
    goal_state: str = "ACTIVE"


@dataclass(frozen=True)
class SnapshotResult:
    restore_point_id: int
    volumes_snapshotted: int
    consistent: bool


class SnapshotPreflightFailed(Exception):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(
            "preflight basarisiz: "
            + "; ".join(f"{r.name}/{r.status.value}" for r in report.results)
        )


class SnapshotService:
    def __init__(
        self,
        gateway: OpenstackGateway,
        provider_factory: Callable[[str], SnapshotProvider],
        manifest_builder: ManifestBuilder | None = None,
    ) -> None:
        self._gateway = gateway
        self._provider_factory = provider_factory
        self._manifest_builder = manifest_builder or ManifestBuilder(gateway)

    def snapshot_instance(
        self,
        session: Session,
        instance_uuid: str,
        options: SnapshotOptions,
    ) -> SnapshotResult:
        ctx = PreflightContext(
            plan_kind=PlanKind.SNAPSHOT,
            gateway=self._gateway,
            instance_uuid=instance_uuid,
            goal_state=options.goal_state,
        )
        report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx)
        if not report.passed:
            raise SnapshotPreflightFailed(report)

        server = ctx.data["server"]
        project_id = ctx.data["project_id"]

        instance_row = session.scalar(
            select(Instance).where(Instance.instance_uuid == server.id)
        )
        if instance_row is None:
            raise SnapshotPreflightFailed(
                ValidationReport(plan_kind=PlanKind.SNAPSHOT),
            )

        targets: list[tuple[SnapshotTarget, SnapshotProvider]] = []
        for volume in self._gateway.list_volumes(project_id):
            if not any(a.server_id == server.id for a in volume.attachments):
                continue
            host = parse_host(volume.host)
            if host.pool is None:
                raise SnapshotPreflightFailed(ValidationReport(plan_kind=PlanKind.SNAPSHOT))
            try:
                provider = self._provider_factory(host.driver or "")
            except ProviderUnavailable as exc:
                raise SnapshotPreflightFailed(ValidationReport(plan_kind=PlanKind.SNAPSHOT)) from exc
            targets.append(
                (
                    SnapshotTarget(
                        image=volume.id,
                        pool=host.pool,
                        project_id=project_id,
                        instance_id=server.id,
                    ),
                    provider,
                )
            )

        if options.require_consistent:
            for _target, _provider in targets:
                self._gateway.quiesce_guest(server.id)

        refs: list[SnapshotRef] = []
        try:
            for target, provider in targets:
                refs.append(provider.snapshot(target, "bkp-"))
        finally:
            if options.require_consistent:
                self._gateway.unquiesce_guest(server.id)

        manifest = self._manifest_builder.build(project_id, server)
        restore_point = RestorePoint(
            kind="snapshot", instance_id=instance_row.id, manifest=manifest,
            status="active",
        )
        session.add(restore_point)
        session.flush()

        for (target, provider), ref in zip(targets, refs, strict=False):
            volume_ref = session.scalar(
                select(VolumeRef).where(
                    VolumeRef.instance_id == instance_row.id,
                    VolumeRef.volume_uuid == target.image,
                )
            )
            session.add(
                VolumeBackup(
                    restore_point_id=restore_point.id,
                    volume_ref_id=volume_ref.id if volume_ref is not None else None,
                    snapshot_ref=f"{target.pool}/{target.image}@{ref.snapshot}",
                    tier="t0",
                    object_manifest={},
                )
            )
        session.commit()
        return SnapshotResult(
            restore_point_id=restore_point.id,
            volumes_snapshotted=len(refs),
            consistent=options.require_consistent,
        )
