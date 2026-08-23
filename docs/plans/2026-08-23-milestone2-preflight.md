# Plan 2: Preflight Motoru (plan → validate → apply) — Implementation Plan

> **Durum: TAMAMLANDI** — plan implement edildi, main'e merge edildi (tarihsel
> kayıt). Kalıcı davranış ve tuzaklar için src/osbak/preflight/NOTES.md ve README'ye bakın.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kontrol çerçevesini inşa et: doğrulama ağacı (PlanKind × Check), her check'in PASS/FAIL + mesaj döndürdüğü `ValidationEngine`, ve gateway'e dayanan ilk check seti (keystone erişim, instance mevcut/durum). Çıktı: `ValidationReport` (passed + resource_delta).

**Architecture:** `osbak.preflight.model` (enum'lar + `CheckResult` + `ValidationReport`) → `engine` (Check ABC + registry + `ValidationEngine.validate`) → `rules/` (erişim/durum kickler). Rules gateway üzerinden konuşur; testler `FakeGateway` ile. Bu, spec §11'deki "her kontrol PASS/FAIL + resource delta, sessiz alternatif yok" davranışının çerçevesidir; provider-spesifik kapasite/yetkinlik/limit incelemeleri ilgili provider milestone'larında eklenir.

**Tech Stack:** Python ≥3.10, mevcut `osbak` paketi, pytest. Yeni bağımlılık yok.

**Spec:** `docs/specs/2026-08-23-osbak-architecture.md` (§11 Pre-flight motoru, §15 state machine) + `docs/adr/ADR-002-manifest-lock-tz.md`

## Global Constraints

- **Fallback kuralı:** `_pick`/çok-anahtar okuma yok, geniş `except Exception` yok. Yalnızca erişim probe'u `openstack.exceptions.SDKException`'ı (dar, anlamlı tek hata türü) yakalar → FAIL. "Instance yok" istisna DEĞİL, deterministik FAIL'dır (engine exception yutmaz; check fırlatırsa gorülür).
- Provider-spesifik incelemeler (kapasite/yetkinlik/limit) BU planın kapsamı DIŞI — Ceph/NetApp milestone'larında gelir; `CheckKind` enum'ı buna hazır.
- `ValidationReport.resource_delta` şimdilik boş dict'tir (model alanı spec'ten); delta hesaplaması restore/snapshot milestone'larında dolar.
- No live infra; testler `tests/fake_gateway.py` ve gerekirse SDKException fırlatan minimal fake ile.
- Manifest katı şema değil; preflight kendi içinde katı tipler kullanır.
- Kuruluş güvenliği: geliştirme/test sırasında canlı OpenStack/Ceph/ONTAP/S3'e bağlanılmaz.

## File Structure

```
src/osbak/preflight/__init__.py
src/osbak/preflight/model.py        # PlanKind, CheckKind, CheckStatus, CheckResult, ValidationReport
src/osbak/preflight/context.py      # PreflightContext
src/osbak/preflight/engine.py       # Check(ABC), register_check, ValidationEngine
src/osbak/preflight/rules/__init__.py
src/osbak/preflight/rules/keystone.py    # keystone_erisim
src/osbak/preflight/rules/instances.py   # instance_mevcut, instance_durum
src/osbak/preflight/NOTES.md
tests/test_preflight_model.py
tests/test_preflight_engine.py
tests/test_preflight_rules.py
```

---

## Task 1: preflight model

**Files:**
- Create: `src/osbak/preflight/__init__.py` (boş)
- Create: `src/osbak/preflight/model.py`
- Create: `tests/test_preflight_model.py`

**Interfaces:**
- Produces: `PlanKind` (SNAPSHOT/BACKUP/RESTORE/ROLLBACK), `CheckKind` (ERISIM/KAPASITE/DURUM/YETKINLIK/LIMIT/CAKISMA), `CheckStatus` (PASS/FAIL), `CheckResult(name, kind, status, message, data)`, `ValidationReport(plan_kind, results, resource_delta)` with `.passed` property and `.by_kind(kind)`.

- [x] **Step 1: Failing test**

`tests/test_preflight_model.py`:
```python
from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
    ValidationReport,
)


def test_check_result_default_data() -> None:
    r = CheckResult(name="x", kind=CheckKind.DURUM, status=CheckStatus.PASS, message="ok")
    assert r.data == {}


def test_report_passed_all_pass() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.SNAPSHOT,
        results=(
            CheckResult("a", CheckKind.ERISIM, CheckStatus.PASS, "ok"),
            CheckResult("b", CheckKind.DURUM, CheckStatus.PASS, "ok"),
        ),
    )
    assert report.passed is True


def test_report_passed_false_on_fail() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.SNAPSHOT,
        results=(CheckResult("a", CheckKind.DURUM, CheckStatus.FAIL, "boom"),),
    )
    assert report.passed is False


def test_report_by_kind_filters() -> None:
    report = ValidationReport(
        plan_kind=PlanKind.BACKUP,
        results=(
            CheckResult("a", CheckKind.ERISIM, CheckStatus.PASS, "ok"),
            CheckResult("b", CheckKind.DURUM, CheckStatus.FAIL, "boom"),
            CheckResult("c", CheckKind.DURUM, CheckStatus.PASS, "ok"),
        ),
    )
    durum = report.by_kind(CheckKind.DURUM)
    assert [r.name for r in durum] == ["b", "c"]
```

- [x] **Step 2: Run to fail** — `pytest tests/test_preflight_model.py -v` → FAIL (modül yok).

- [x] **Step 3: Implement**

`src/osbak/preflight/model.py`:
```python
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
```

- [x] **Step 4: Run to pass** — `pytest tests/test_preflight_model.py -v` → PASS.

- [x] **Step 5: Commit**

```bash
git add src/osbak/preflight tests/test_preflight_model.py
git commit -m "feat: preflight model (PlanKind, CheckKind, CheckResult, ValidationReport)"
```

---

## Task 2: Check ABC + registry + ValidationEngine

**Files:**
- Create: `src/osbak/preflight/context.py`
- Create: `src/osbak/preflight/engine.py`
- Create: `tests/test_preflight_engine.py`

**Interfaces:**
- Consumes: `osbak.preflight.model`, `OpenstackGateway` (Protocol), DTO'lar.
- Produces: `PreflightContext(plan_kind, gateway, session=None, instance_uuid=None, project_id=None, goal_state=None, data={})`; `Check` ABC (`kind`, `name`, `applies_to: frozenset[PlanKind]`, `run(ctx) -> CheckResult`); `register_check(cls)` decorator; `checks_for(plan_kind) -> list[type[Check]]`; `ValidationEngine.validate(kind, ctx, only=None) -> ValidationReport`.

**Registry sözleşmesi:** aynı (PlanKind, name) ikilisi ikinci kez kaydedilirse `ValueError` (deterministik hata, sessiz üzerine yazma yok). `validate` `only` parametresi verilirse yalnız o name'lere sahip check'leri koşar (apply yeniden-doğrulama için).

- [x] **Step 1: Failing test**

`tests/test_preflight_engine.py`:
```python
import pytest

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, ValidationEngine, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind
from tests.fake_gateway import FakeGateway


@register_check
class AlwaysPass(Check):
    kind = CheckKind.DURUM
    name = "always_pass"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP})

    def run(self, ctx: PreflightContext) -> CheckResult:
        return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")


@register_check
class SnapshotOnlyCheck(Check):
    kind = CheckKind.ERISIM
    name = "snapshot_only"
    applies_to = frozenset({PlanKind.SNAPSHOT})

    def run(self, ctx: PreflightContext) -> CheckResult:
        return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")


def test_validate_runs_applicable_checks() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx)
    assert {r.name for r in report.results} == {"always_pass", "snapshot_only"}
    assert report.passed is True


def test_validate_backup_excludes_snapshot_only() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.BACKUP, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(PlanKind.BACKUP, ctx)
    assert {r.name for r in report.results} == {"always_pass"}


def test_validate_only_restricts_to_named_checks() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["snapshot_only"])
    assert [r.name for r in report.results] == ["snapshot_only"]


def test_duplicate_registration_raises() -> None:
    with pytest.raises(ValueError):

        @register_check
        class Duplicate(AlwaysPass):
            name = "always_pass"
```

- [x] **Step 2: Run to fail** — `pytest tests/test_preflight_engine.py -v` → FAIL.

- [x] **Step 3: Implement**

`src/osbak/preflight/context.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from osbak.discovery.gateway import OpenstackGateway
from osbak.preflight.model import PlanKind


@dataclass
class PreflightContext:
    plan_kind: PlanKind
    gateway: OpenstackGateway
    session: Any = None
    instance_uuid: str | None = None
    project_id: str | None = None
    goal_state: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
```

`src/osbak/preflight/engine.py`:
```python
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
    for plan_kind in cls.applies_to:
        key = (plan_kind, cls.name)
        if key in _REGISTRY:
            raise ValueError(f"duplicate check registration: {plan_kind.value}/{cls.name}")
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
```

- [x] **Step 4: Run to pass** — `pytest tests/test_preflight_engine.py -v` → PASS.

- [x] **Step 5: Commit**

```bash
git add src/osbak/preflight/context.py src/osbak/preflight/engine.py tests/test_preflight_engine.py
git commit -m "feat: Check ABC, registry, ValidationEngine"
```

---

## Task 3: rules — keystone erişim + instance mevcut/durum

**Files:**
- Create: `src/osbak/preflight/rules/__init__.py` (boş)
- Create: `src/osbak/preflight/rules/keystone.py`
- Create: `src/osbak/preflight/rules/instances.py`
- Create: `tests/test_preflight_rules.py`

**Interfaces:**
- Consumes: `osbak.preflight.engine.Check`, `osbak.preflight.context.PreflightContext`, `osbak.discovery.gateway` (parse etmeye gerek yok — sadece list_*), DTO'lar.
- Produces:
  - `keystone_erisim` (kind ERISIM, applies_to tüm PlanKind'lar): `ctx.gateway.list_projects()` çalışır → PASS (data: `{"projects": n}`); `openstack.exceptions.SDKException` fırlatırsa → FAIL (dar, anlamlı tek hata türü; başka istisna yakalanmaz ve yukarı fırlar).
  - `instance_mevcut` (kind DURUM, applies_to SNAPSHOT/BACKUP/ROLLBACK): `ctx.instance_uuid` verilmişse; gateway projelerini ve sunucularını tarar; bulunursa PASS (data: `{"project_id": ..., "server_id": ...}`), hiçbir projede yoksa FAIL; `instance_uuid` None ise FAIL.
  - `instance_durum` (kind DURUM, applies_to SNAPSHOT/BACKUP): `ctx.goal_state` verilmişse server'ın `status` ile birebir eşleşmesini ister → eşleşirse PASS, eşleşmezse FAIL; `goal_state` None ise skip etmek yerine PASS (durum hedefi yok = kısıt yok). `instance_mevcut`'tan sonra koşar; server bilgisini `ctx.data["server"]` üzerinden alır (rules sırasını engine garanti etmez — instance_durum, server'ı `ctx` üzerinden bulamazsa FAIL).

**Davranış notu:** `instance_durum` ve `instance_mevcut` aynı server aramasını tekrar etmemek için `ctx.data` paylaşır — `instance_mevcut` `ctx.data["server"] = server` yazar; `instance_durum` onu okur. Sıra bağımlılığı registry kayıt sırasından gelir; bu plan'da ok ama kırılgan olabilir — alternatifi sunmak yerine bu deterministik sözleşmeyi kabul ediyoruz (iki check de server yoksa FAIL).

- [x] **Step 1: Failing test**

`tests/test_preflight_rules.py`:
```python
import openstack

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import CheckStatus, PlanKind
from osbak.discovery.gateway import ProjectInfo, ServerInfo
from tests.fake_gateway import FakeGateway


class _SdkErrorGateway:
    def list_projects(self):
        raise openstack.exceptions.SDKException("auth failed")

    def list_servers(self, project_id: str):
        return []


def test_keystone_erisim_pass() -> None:
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")]),
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["keystone_erisim"])
    assert report.results[0].status is CheckStatus.PASS
    assert report.results[0].data["projects"] == 1


def test_keystone_erisim_fail_on_sdk_error() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=_SdkErrorGateway())
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["keystone_erisim"])
    assert report.results[0].status is CheckStatus.FAIL


def test_instance_mevcut_pass_and_data() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="i-1"
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.PASS
    assert report.results[0].data["server_id"] == "i-1"


def test_instance_mevcut_fail_when_missing() -> None:
    gateway = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")], servers={"pid-1": []})
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="nope"
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.FAIL


def test_instance_mevcut_fail_when_none() -> None:
    gateway = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")])
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gateway)
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.FAIL


def test_instance_durum_pass_and_fail() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=gateway,
        instance_uuid="i-1",
        goal_state="ACTIVE",
    )
    report = ValidationEngine().validate(
        PlanKind.SNAPSHOT, ctx, only=["instance_mevcut", "instance_durum"]
    )
    assert report.passed is True
    fail_ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=gateway,
        instance_uuid="i-1",
        goal_state="STOPPED",
    )
    fail_report = ValidationEngine().validate(
        PlanKind.SNAPSHOT, fail_ctx, only=["instance_mevcut", "instance_durum"]
    )
    assert any(r.status is CheckStatus.FAIL for r in fail_report.results)
```

- [x] **Step 2: Run to fail** — `pytest tests/test_preflight_rules.py -v` → FAIL.

- [x] **Step 3: Implement**

`src/osbak/preflight/rules/keystone.py`:
```python
from __future__ import annotations

import openstack

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
)


@register_check
class KeystoneErisim(Check):
    kind = CheckKind.ERISIM
    name = "keystone_erisim"
    applies_to = frozenset(PlanKind)

    def run(self, ctx: PreflightContext) -> CheckResult:
        try:
            projects = ctx.gateway.list_projects()
        except openstack.exceptions.SDKException as exc:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, str(exc))
        return CheckResult(
            self.name,
            self.kind,
            CheckStatus.PASS,
            f"{len(projects)} proje",
            {"projects": len(projects)},
        )
```

`src/osbak/preflight/rules/instances.py`:
```python
from __future__ import annotations

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind


@register_check
class InstanceMevcut(Check):
    kind = CheckKind.DURUM
    name = "instance_mevcut"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP, PlanKind.ROLLBACK})

    def run(self, ctx: PreflightContext) -> CheckResult:
        uuid = ctx.instance_uuid
        if uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        for project in ctx.gateway.list_projects():
            for server in ctx.gateway.list_servers(project.id):
                if server.id == uuid:
                    ctx.data["server"] = server
                    return CheckResult(
                        self.name,
                        self.kind,
                        CheckStatus.PASS,
                        f"bulundu: {project.id}/{server.id}",
                        {"project_id": project.id, "server_id": server.id},
                    )
        return CheckResult(self.name, self.kind, CheckStatus.FAIL, f"instance yok: {uuid}")


@register_check
class InstanceDurum(Check):
    kind = CheckKind.DURUM
    name = "instance_durum"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP})

    def run(self, ctx: PreflightContext) -> CheckResult:
        if ctx.goal_state is None:
            return CheckResult(self.name, self.kind, CheckStatus.PASS, "durum hedefi yok")
        server = ctx.data.get("server")
        if server is None or server.status != ctx.goal_state:
            return CheckResult(
                self.name,
                self.kind,
                CheckStatus.FAIL,
                f"beklenen: {ctx.goal_state}, gerçek: {server.status if server else 'yok'}",
            )
        return CheckResult(self.name, self.kind, CheckStatus.PASS, f"durum: {server.status}")
```

- [x] **Step 4: Run to pass** — `pytest tests/test_preflight_rules.py -v` → PASS.

- [x] **Step 5: Commit**

```bash
git add src/osbak/preflight/rules tests/test_preflight_rules.py
git commit -m "feat: preflight rules (keystone erisim, instance mevcut/durum)"
```

---

## Task 4: NOTES dokümantasyonu + tüm suite + kapanış

**Files:**
- Create: `src/osbak/preflight/NOTES.md`
- Modify: `docs/plans/2026-08-23-milestone2-preflight.md` (checkbox'ları işaretle — bu görev implementer'ın raporunda not eder; dosyayı elle değiştirmek zorunlu değil)

**Interfaces:**
- Consumes: Task 1-3 çıktıları.

- [x] **Step 1: NOTES yaz**

`src/osbak/preflight/NOTES.md`:
```markdown
# preflight — notlar (LLM'ler için)

Ne: her işlem öncesi çalışan doğrulama ağacı (plan → validate → apply).

Neden:
- `ValidationEngine.validate(plan_kind, ctx, only=...)` → `ValidationReport`; PASS/FAIL
  + mesaj + data. `only` apply öncesi kısmi yeniden-doğrulama içindir.
- Check kaydı `register_check` ile; (PlanKind, name) çakışması ValueError (sessiz
  üzerine yazma yok).
- Erişim probe'u yalnızca `openstack.exceptions.SDKException` yakalar (dar); diğer
  istisnalar yukarı fırlar — engine istisna yutmaz.

Tuzaklar:
- `instance_mevcut` `ctx.data["server"]`'ı yazar, `instance_durum` okur — registry
  sırasına bağlı. Server yoksa ikisi de hangi sırada olursa FAIL.
- Kapasite/yetkinlik/limit incelemeleri provider milestone'larında gelir
  (CheckKind hazır); resource_delta restore/snapshot milestone'ında dolar.
- Fallback kuralı: çok-anahtar okuma yok; "instance yok" FAIL'dır, istisna değil.
```

- [x] **Step 2: Tüm suite** — `pytest -v` → tümü (önceki 28 + yeni) PASS, pristine.

- [x] **Step 3: Commit**

```bash
git add src/osbak/preflight/NOTES.md
git commit -m "docs: preflight NOTES"
```

---

## Self-Review / Execution Handoff

Tasks 1-4, spec §11'in çerçevesini (doğrulama ağacı + ilk gerçek incelemeler) kurar; çıktı çalışan, test edilebilir, canlı ağa bağlanmayan modüldür. Sonraki plan (Plan 3): snapshot orkestrasyonu — preflight'ı `osbak` iş akışına bağlar (Ceph provider + quiesce).

**Execution:** Subagent-Driven (her görev: implementer → task review → fix loop → final whole-branch review → merge).
