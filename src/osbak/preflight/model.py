from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class PlanKind(str, enum.Enum):
    SNAPSHOT = "snapshot"
    BACKUP = "backup"
    RESTORE = "restore"
    ROLLBACK = "rollback"


class CheckKind(str, enum.Enum):
    ERISIM = "erisim"
    KAPASITE = "kapasite"
    DURUM = "durum"
    YETKINLIK = "yetkinlik"
    LIMIT = "limit"
    CAKISMA = "cakisma"


class CheckStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    name: str
    kind: CheckKind
    status: CheckStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    plan_kind: PlanKind
    results: tuple[CheckResult, ...] = ()
    resource_delta: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(result.status is CheckStatus.PASS for result in self.results)

    def by_kind(self, kind: CheckKind) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if result.kind is kind)
