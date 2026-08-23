from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from osbak.discovery.gateway import OpenstackGateway
from osbak.models import RestoreOp, RestorePoint
from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import PlanKind, ValidationReport
from osbak.preflight.rules import keystone, restore  # noqa: F401  (register)
from osbak.restore.executor import RebuildExecutor
from osbak.restore.gateway_mutations import RestoreGateway
from osbak.restore.model import (
    RestoreOptions,
    RestorePlanError,
    options_to_dict,
    plan_from_dict,
    plan_to_dict,
)
from osbak.restore.planner import RestorePlanner


class RestorePreflightFailed(Exception):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(
            "preflight basarisiz: "
            + "; ".join(f"{r.name}/{r.status.value}" for r in report.results)
        )


@dataclass(frozen=True)
class RestoreApplyResult:
    restore_op_id: int
    state: str
    server_id: str | None


class RestoreService:
    def __init__(
        self,
        session: Any,
        gateway: OpenstackGateway | None,
        restore_gateway_factory: Callable[[], RestoreGateway],
    ) -> None:
        # gateway yalniz apply'de (preflight) kullanilir; plan/show DB-only oldugundan
        # CLI None gecirebilir. apply'de gateway yoksa PreflightContext kurulamaz ->
        # bu durum yalniz apply CLI'da olusmaz (orada her zaman SDKGateway gecilir).
        self._session = session
        self._gateway = gateway
        self._restore_gateway_factory = restore_gateway_factory

    def plan(
        self,
        restore_point_id: int,
        options: RestoreOptions,
        created_by: str | None = None,
    ) -> int:
        point = self._session.get(RestorePoint, restore_point_id)
        if point is None:
            raise RestorePlanError(f"restore point yok: {restore_point_id}")
        rplan = RestorePlanner(point.manifest, options, restore_point_id).build()
        op = RestoreOp(
            restore_point_id=restore_point_id,
            strategy=rplan.strategy.value,
            state="PLANNED",
            mapping={},
            plan=plan_to_dict(rplan),
            options=options_to_dict(options),
            created_by=created_by,
        )
        self._session.add(op)
        self._session.commit()
        return op.id

    def apply(
        self, restore_op_id: int, created_by: str | None = None
    ) -> RestoreApplyResult:
        op = self._session.get(RestoreOp, restore_op_id)
        if op is None:
            raise RestorePlanError(f"restore op yok: {restore_op_id}")
        if op.state != "PLANNED":
            raise RestorePlanError(f"yeniden plan gerekli (state={op.state})")

        if self._gateway is None:
            raise RestorePlanError("apply icin gateway gerekli")

        point = self._session.get(RestorePoint, op.restore_point_id)
        if point is None:
            op.state = "FAILED"
            op.error = "restore point silinmis"
            op.finished_at = self._utcnow()
            self._session.commit()
            raise RestorePlanError("restore point silinmis — yeniden plan")

        manifest = point.manifest
        ctx = PreflightContext(
            plan_kind=PlanKind.RESTORE,
            gateway=self._gateway,
            instance_uuid=manifest["instance"]["id"],
            project_id=manifest["project_id"],
        )
        report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
        if not report.passed:
            op.state = "FAILED"
            op.error = "preflight: " + "; ".join(
                f"{r.name}/{r.status.value}" for r in report.results
            )
            op.finished_at = self._utcnow()
            self._session.commit()
            raise RestorePreflightFailed(report)

        op.state = "PREFLIGHT_PASS"
        self._session.commit()

        rplan = plan_from_dict(op.plan)
        mapping = RebuildExecutor(
            self._restore_gateway_factory(), self._session
        ).execute(op, rplan)
        return RestoreApplyResult(
            restore_op_id=op.id,
            state=op.state,
            server_id=mapping.get("server"),
        )

    def show(self, restore_op_id: int) -> RestoreOp:
        op = self._session.get(RestoreOp, restore_op_id)
        if op is None:
            raise RestorePlanError(f"restore op yok: {restore_op_id}")
        return op

    @staticmethod
    def _utcnow():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)
