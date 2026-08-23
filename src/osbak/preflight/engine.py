from __future__ import annotations

from abc import ABC, abstractmethod

from osbak.preflight.context import PreflightContext
from osbak.preflight.model import CheckKind, CheckResult, PlanKind, ValidationReport


class Check(ABC):
    kind: CheckKind
    name: str
    applies_to: frozenset[PlanKind]

    @abstractmethod
    def run(self, ctx: PreflightContext) -> CheckResult: ...


_REGISTRY: dict[tuple[PlanKind, str], type[Check]] = {}


def register_check(cls: type[Check]) -> type[Check]:
    keys = [(plan_kind, cls.name) for plan_kind in cls.applies_to]
    for key in keys:
        if key in _REGISTRY:
            raise ValueError(f"duplicate check registration: {key[0].value}/{key[1]}")
    for key in keys:
        _REGISTRY[key] = cls
    return cls


def checks_for(plan_kind: PlanKind) -> list[type[Check]]:
    return [
        cls
        for (kind, _name), cls in _REGISTRY.items()
        if kind is plan_kind
    ]


class ValidationEngine:
    def validate(
        self, plan_kind: PlanKind, ctx: PreflightContext, only: list[str] | None = None
    ) -> ValidationReport:
        results = []
        for cls in checks_for(plan_kind):
            if only is not None and cls.name not in only:
                continue
            check = cls()
            results.append(check.run(ctx))
        return ValidationReport(plan_kind=plan_kind, results=tuple(results))
