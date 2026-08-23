# Plan 6: Restore CLI + servis katmanı (iki fazlı plan-apply, kalıcı plan) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore'u komut satırından kullanılabilir kıl: iki fazlı ve kalıcı plan. `osbak restore plan <restore-point-id>` manifest'ten `RestorePlan` üretir, adımları `RestoreOp.plan` JSONB'ye yazar (state=PLANNED). `osbak restore apply <op-id>` saklı adımlarla `RebuildExecutor`'ı yürütür (PLANNED → PREFLIGHT_PASS → EXECUTING → DONE|FAILED — spec §15). Plan→apply arası durum değişirse (restore point silindiyse / op PLANNED değilse) apply REDDEDİLİR, yeniden plan istenir (§15). Preflight bağlanır: `OrjinalInstanceYok` kuralı (ADR-001 rebuild: orijinal instance silinmiş olmalı).

**Architecture:** `restore/restore_service.py` (RestoreService: plan/apply/show) → `models.RestoreOp.plan` JSONB kolonu (adımlar, options, resource_delta) + `restore/model.py` serialization (`plan_to_dict`/`plan_from_dict`) → `preflight/rules/restore.py` (`OrjinalInstanceYok`, PlanKind.RESTORE) → executor refactor: `RebuildExecutor.execute(op, plan)` artık op'yu KENDİSİ açmaz; mevcut op'yu EXECUTING→DONE/FAILED'e geçirir → `cli.py` `restore plan/apply/show` komutları.

**Tech Stack:** Python ≥3.10, mevcut osbak, pytest. Yeni zorunlu bağımlılık YOK.

**Spec:** `docs/specs/2026-08-23-osbak-architecture.md` (§8 restore, §15 state machine, §16 API yüzeyi), `docs/adr/ADR-001-rollback-strategies.md` (rebuild: orijinal yoksa), `docs/plans/2026-08-23-milestone5-restore.md` (çekirdek zaten yapıldı, bu plan wiring yapar).

## Global Constraints

- **Fallback kuralı:** YOK — geniş `except Exception` yok (tek izinli teardown+re-raise; Task 4 executor'da). Sessiz alternatif yol yok. Durum değişikliği varsa apply sessizce "olduğu gibi yürütmez" — sesli reddeder.
- **İki fazlı, kalıcı:** plan adımları DB'de saklanır (`RestoreOp.plan`). Apply saklı adımları çözer (yeniden planlamaz/kıyaslamaz). §15 "plan→apply arası durum değişirse apply reddedilir": apply, restore point'in HÂLÂ VAR olduğunu ve op.state == "PLANNED" olduğunu doğrular; değilse `RestorePlanError("yeniden plan")`.
- **Preflight:** apply öncesi `ValidationEngine.validate(PlanKind.RESTORE, ctx)` koşulur; `OrjinalInstanceYok` PASS geçmeli. FAIL → op FAILED + `RestorePreflightFailed` (SnapshotPreflightFailed deseni). `keystone_erisim` zaten `frozenset(PlanKind)` → RESTORE'a da uygulanır (inyorç değil, istenen — bağlantı erişimini doğrular).
- **Executor refactor:** `RebuildExecutor.execute(op: RestoreOp, plan: RestorePlan)` — op'yu **kendisi açmaz**; çağıran (service) PLANNED op'yu hazırlar. Executor `op.state`'i EXECUTING'e çeker, bitirir: DONE (mapping tam, error None) | FAILED (mapping kısmi korunur, error dolu). JSON kalıcılık deseni korunur (lokal dict + bitişte `op.mapping = dict(mapping)` yeni nesne ataması — `expire_on_commit=False` tuzağı).
- **CLI kapsamı:** `restore plan/apply/show`. HTTP API, scheduler, RBAC KAPSAM DIŞI (ayrı milestone). Canlı mutasyon (`SDKRestoreGateway`) hâlâ NotImplementedError — CLI apply testleri `FakeRestoreGateway` ile; canlı mutasyon provider milestone'a kaldı. `restore show` salt-okunur (DB'den op okur; gateway yok).
- **Model değişikliği:** `RestoreOp.plan`: `Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)` + `RestoreOp.options`: `Mapped[Optional[dict]]`. `init_db` create_all'ı yeni kolonları test DB'lerinde kurar; mevcut/üretim DB için ALTER notu Task 5 NOTES'a.
- **Serialization:** `restore/model.py` içinde `plan_to_dict(RestorePlan) -> dict` ve `plan_from_dict(dict, restore_point_id) -> RestorePlan`. PlanStep → dict (seq/action/key/payload), RestorePlan → {strategy, restore_point_id, resource_delta, steps}. JSONB-güvenli (payload dict'leri zaten JSON-uyumlu).

## File Structure

```
src/osbak/restore/restore_service.py  # RestoreService (plan/apply/show), RestoreApplyResult, RestorePreflightFailed
src/osbak/restore/model.py            # + plan_to_dict/plan_from_dict (serialization)
src/osbak/restore/executor.py         # refactor: execute(op, plan) — op açmaz
src/osbak/models.py                   # RestoreOp.plan + RestoreOp.options (JSON, nullable)
src/osbak/preflight/rules/restore.py  # OrjinalInstanceYok (PlanKind.RESTORE)
src/osbak/cli.py                      # restore plan/apply/show komutları
src/osbak/restore/NOTES.md            # güncelle (model kolonu, iki faz, preflight, canlı mutasyon)
tests/test_restore_model.py           # + plan serialization testleri
tests/test_restore_executor.py        # refactor imzasına uygun güncelle (execute(op, plan))
tests/test_restore_service.py         # RestoreService plan/apply/show + preflight + §15 reddi
tests/test_preflight_restore.py       # OrjinalInstanceYok kuralı
tests/test_cli.py                     # restore plan/apply/show wiring
```

HTTP/API: KAPSAM DIŞI (ayrı milestone); bu plan CLI + servis + test üretir.

---

## Task 1: model — `RestoreOp.plan` + `RestoreOp.options` JSONB + serialization

**Files:**
- Modify: `src/osbak/models.py` (RestoreOp'a 2 kolon)
- Modify: `src/osbak/restore/restore_service.py` (YOK — Task 4; burada değil)
- Modify: `src/osbak/restore/model.py` (serialization helpers)
- Modify: `tests/test_restore_model.py`

**Interfaces:**
- Produces (`restore/model.py`):
  - `plan_to_dict(plan: RestorePlan) -> dict` — `{"strategy": plan.strategy.value, "restore_point_id": plan.restore_point_id, "resource_delta": dict(plan.resource_delta), "steps": [{"seq","action","key","payload"}...]}`  (payload shallow-copy `dict(s.payload)` — PlanStep frozen, payload dict mutable).
  - `plan_from_dict(data: dict) -> RestorePlan` — tersi; `RestoreStrategy(data["strategy"])`, `tuple(PlanStep(...))`, `dict(resource_delta)`.
  - `options_to_dict(options: RestoreOptions) -> dict` — `{"strategy": strategy.value, "instance_name": ..., "availability_zone": ..., "keep_ip": ...}`.
- `RestoreOp` (models.py) iki yeni kolon: `plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)` ve `options: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)`.
- `init_db` değişmez: `create_all` yeni tablolar+yeni kolonlar eksikse kurar; mevcut/üretim DB'de kolon EKLEMEZ → üretim DB ALTER notu Task 5 NOTES'a.

- [ ] **Step 1: Failing test**

`tests/test_restore_model.py`'ye ekle:
```python
from osbak.restore.model import (
    PlanStep,
    RestoreOptions,
    RestorePlan,
    RestoreStrategy,
    options_to_dict,
    plan_from_dict,
    plan_to_dict,
)


def test_plan_serialization_round_trip() -> None:
    plan = RestorePlan(
        strategy=RestoreStrategy.REBUILD,
        restore_point_id=3,
        steps=(
            PlanStep(seq=0, action="ensure_security_group_shell",
                     key="sg:web", payload={"name": "web"}),
            PlanStep(seq=1, action="create_volume", key="vol:v-1",
                     payload={"size_gb": 10}),
        ),
        resource_delta={"volumes": 1, "ports": 0, "security_groups": 1,
                        "flavors": 1, "servers": 1},
    )
    data = plan_to_dict(plan)
    restored = plan_from_dict(data)
    assert isinstance(restored, RestorePlan)
    assert restored.strategy is RestoreStrategy.REBUILD
    assert restored.restore_point_id == 3
    assert restored.resource_delta == plan.resource_delta
    assert [(s.seq, s.action, s.key) for s in restored.steps] == [
        (0, "ensure_security_group_shell", "sg:web"),
        (1, "create_volume", "vol:v-1"),
    ]
    assert restored.steps[1].payload == {"size_gb": 10}


def test_plan_serialization_round_trip_empty_steps() -> None:
    plan = RestorePlan(strategy=RestoreStrategy.REBUILD, restore_point_id=1,
                       steps=(), resource_delta={})
    assert plan_from_dict(plan_to_dict(plan)).steps == ()


def test_options_to_dict_serializes_enum() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=False,
                          instance_name="web-x")
    assert options_to_dict(opts) == {
        "strategy": "rebuild",
        "instance_name": "web-x",
        "availability_zone": None,
        "keep_ip": False,
    }
```

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_restore_model.py -v` → 3 yeni test FAIL.

- [ ] **Step 3: Implement**

`src/osbak/models.py` RestoreOp'a ekle (mapping'den sonra):
```python
    plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    options: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
```

`src/osbak/restore/model.py`'ye ecir fonksiyonlar (alttan):
```python
def plan_to_dict(plan: RestorePlan) -> dict:
    return {
        "strategy": plan.strategy.value,
        "restore_point_id": plan.restore_point_id,
        "resource_delta": dict(plan.resource_delta),
        "steps": [
            {"seq": s.seq, "action": s.action, "key": s.key,
             "payload": dict(s.payload)}
            for s in plan.steps
        ],
    }


def plan_from_dict(data: dict) -> RestorePlan:
    return RestorePlan(
        strategy=RestoreStrategy(data["strategy"]),
        restore_point_id=data["restore_point_id"],
        steps=tuple(
            PlanStep(seq=s["seq"], action=s["action"], key=s["key"],
                     payload=dict(s["payload"]))
            for s in data["steps"]
        ),
        resource_delta=dict(data["resource_delta"]),
    )


def options_to_dict(options: RestoreOptions) -> dict:
    return {
        "strategy": options.strategy.value,
        "instance_name": options.instance_name,
        "availability_zone": options.availability_zone,
        "keep_ip": options.keep_ip,
    }
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_restore_model.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -q` → tümü pass.

- [ ] **Step 6: Commit**

```bash
git add src/osbak/models.py src/osbak/restore/model.py tests/test_restore_model.py
git commit -m "feat: RestoreOp plan/options JSONB kolonlari + plan serialization"
```

---

## Task 2: preflight — `OrjinalInstanceYok` kuralı (PlanKind.RESTORE)

**Files:**
- Create: `src/osbak/preflight/rules/restore.py`
- Create: `tests/test_preflight_restore.py`

**Interfaces:**
- Produces: `OrjinalInstanceYok(Check)` — `kind = CheckKind.CAKISMA`, `name = "orjinal_instance_yok"`, `applies_to = frozenset({PlanKind.RESTORE})`.
  - `ctx.instance_uuid` yoksa FAIL "instance belirtilmedi".
  - `ctx.gateway.list_projects()` × `list_servers(project.id)` içinde `server.id == ctx.instance_uuid` VARSA → FAIL "orijinal instance hala mevcut: <uuid> — once sil/durdur" (rebuild önkoşulu ADR-001: orijinal YOK olmalı).
  - Yoksa → PASS "orijinal instance yok — rebuild uygun".
- `keystone_erisim` zaten `applies_to = frozenset(PlanKind)` → RESTORE validate'ında da koşar (istenen: bağlantı erişimini doğrular).
- Kayıt için `restore_service` import edecek (Task 4): `from osbak.preflight.rules import restore` (register_check çağrılarını tetikler).

- [ ] **Step 1: Failing test**

`tests/test_preflight_restore.py`:
```python
from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import CheckStatus, PlanKind
from osbak.preflight.rules import restore  # noqa: F401  (register)
from tests.fake_gateway import FakeGateway


def _server(pid="p-1"):
    return ServerInfo(id="orig-uuid", name="web", project_id=pid,
                      status="ACTIVE", flavor_id="f1")


def test_orjinal_instance_yok_pass_when_absent() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw,
                           instance_uuid="orig-uuid")
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.PASS
    assert report.passed


def test_orjinal_instance_yok_fail_when_still_present() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")],
                     servers={"p-1": [_server()]})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw,
                           instance_uuid="orig-uuid")
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.FAIL
    assert "hala mevcut" in found.message
    assert not report.passed


def test_orjinal_instance_yok_requires_uuid() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw)
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.FAIL
    assert "belirtilmedi" in found.message
```

(FakeGateway imzaları `tests/fake_gateway.py`'den doğrulandı: `projects: list[ProjectInfo]`, `servers: dict[str, list[ServerInfo]]` — raw dict DEĞİL, tipik nesneler.)

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_preflight_restore.py -v` → FAIL (restore kuralı yok).

- [ ] **Step 3: Implement**

`src/osbak/preflight/rules/restore.py`:
```python
from __future__ import annotations

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
)


@register_check
class OrjinalInstanceYok(Check):
    kind = CheckKind.CAKISMA
    name = "orjinal_instance_yok"
    applies_to = frozenset({PlanKind.RESTORE})

    def run(self, ctx: PreflightContext) -> CheckResult:
        uuid = ctx.instance_uuid
        if uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        for project in ctx.gateway.list_projects():
            for server in ctx.gateway.list_servers(project.id):
                if server.id == uuid:
                    return CheckResult(
                        self.name, self.kind, CheckStatus.FAIL,
                        f"orijinal instance hala mevcut: {uuid} — once sil/durdur",
                    )
        return CheckResult(self.name, self.kind, CheckStatus.PASS,
                           "orijinal instance yok — rebuild uygun")
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_preflight_restore.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -q` → tümü pass (yeni kural diğer PlanKind'leri etkilemez; REM boost yok).

- [ ] **Step 6: Commit**

```bash
git add src/osbak/preflight/rules/restore.py tests/test_preflight_restore.py
git commit -m "feat: preflight OrjinalInstanceYok kurali (PlanKind.RESTORE)"
```


---

## Task 3: executor refactor — `execute(op, plan)` (iki fazlı uyum)

**Files:**
- Modify: `src/osbak/restore/executor.py` — imza `execute(op: RestoreOp, plan: RestorePlan) -> dict[str, Any]`
- Modify: `tests/test_restore_executor.py` — op'yu test kendi kurar

**Neden:** İki fazlı akışta op'yu service (`RestoreService.plan`) PLANNED olarak yaratır; executor op'yu ÜRETMEZ, sadece EXECUTING→DONE/FAILED geçişini yapar. `created_by` parametresi executor'dan çıkar (service.plan'a taşınır).

**JSON kalıcılık deseni (korunur):** op zaten DB'de (PLANNED, mapping={}); executor lokal `mapping` kurar, bitişte `op.mapping = dict(mapping)` (YENİ nesne) → SQLAlchemy değişikliği algılar. `copy` importu executor'dan kalkar (INSERT artık burada yok). EXECUTING anında mapping YAZILMAZ (op.mapping PLANNED'den `{}` kalır); yalnızca bitişte (DONE/FAILED) dolu `dict(mapping)` YENİ nesne olarak atanır → PLANNED'deki `{}` ile fark algılanır.

- [ ] **Step 1: Failing test**

`tests/test_restore_executor.py` — `build_plan()` korunur; her teste `_planned_op` helper'ı ile op kurulur; tüm çağrılar `exc.execute(op, plan)` olur:
```python
import pytest

from osbak.models import RestoreOp
from osbak.restore.executor import RebuildExecutor
from osbak.restore.model import PlanStep, RestoreOptions, RestorePlan, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest, make_manifest_with_group_ref


def build_plan():
    return RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()


def _planned_op(session, plan):
    op = RestoreOp(restore_point_id=plan.restore_point_id, strategy=plan.strategy.value,
                   state="PLANNED", mapping={})
    session.add(op)
    session.commit()
    return op


def test_execute_creates_all_resources_and_records_op(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    op = _planned_op(session, plan)
    mapping = exc.execute(op, plan)

    assert gw.created["servers"][0]["volumes"] == [mapping["volumes"]["v-root"],
                                                   mapping["volumes"]["v-data"]]
    assert gw.created["servers"][0]["ports"] == [mapping["ports"]["port-1"]]
    assert gw.created["servers"][0]["sgs"] == [mapping["security_groups"]["web"]]

    assert op.strategy == "rebuild"
    assert op.state == "DONE"
    assert op.error is None
    assert op.finished_at is not None

    session.expire_all()
    op2 = session.query(RestoreOp).one()
    assert op2.mapping["server"] == mapping["server"]
    assert set(op2.mapping["volumes"]) == {"v-root", "v-data"}
    assert set(op2.mapping["ports"]) == {"port-1"}
    assert set(op2.mapping["security_groups"]) == {"web"}


def test_execute_sg_rules_reference_created_shell(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    exc.execute(_planned_op(session, plan), plan)
    rule_entry = gw.created["sg_rules"][0]
    assert rule_entry["id"] == gw.created["security_groups"][0]["id"]
    assert rule_entry["rules"][0]["protocol"] == "tcp"


def test_execute_sg_rules_remote_group_id_resolved_to_new_id(session) -> None:
    plan = RestorePlanner(make_manifest_with_group_ref(),
                          RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    mapping = exc.execute(_planned_op(session, plan), plan)
    rule_by_sg = {e["id"]: e["rules"] for e in gw.created["sg_rules"]}
    db_rule = rule_by_sg[mapping["security_groups"]["db"]][0]
    assert db_rule["remote_group_id"] == mapping["security_groups"]["web"]
    assert "remote_group_name" not in db_rule


def test_execute_unknown_action_marks_failed(session) -> None:
    plan = RestorePlan(strategy=RestoreStrategy.REBUILD, restore_point_id=1,
                       steps=(PlanStep(seq=0, action="warp", key="x", payload={}),),
                       resource_delta={})
    exc = RebuildExecutor(FakeRestoreGateway(), session)
    try:
        exc.execute(_planned_op(session, plan), plan)
        assert False
    except RestorePlanError as exc2:
        assert "bilinmeyen adim" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "bilinmeyen adim" in op.error
    assert op.finished_at is not None


def test_execute_failure_marks_failed_and_raises(session) -> None:
    class ExplodingGateway(FakeRestoreGateway):
        def create_volume(self, *a, **k):
            raise RuntimeError("boom")

    gw = ExplodingGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    try:
        exc.execute(_planned_op(session, plan), plan)
        assert False
    except RestorePlanError as exc2:
        assert "boom" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "boom" in op.error
    assert op.finished_at is not None

    session.expire_all()
    op = session.query(RestoreOp).one()
    assert set(op.mapping["security_groups"]) == {"web"}
    assert op.mapping["volumes"] == {}
```

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_restore_executor.py -v` → FAIL (imza uyumsuz + op kurulumu).

- [ ] **Step 3: Implement**

`src/osbak/restore/executor.py`:
```python
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
        # NOT: op'yu BU MODUL YOKARATMAZ — service PLANNED olarak yaratir (iki fazli).
        # JSON kolona ayni-nesne ici mutasyon izlenmez (MutableDict yok).
        # EXECUTING'de mapping YAZILMAZ (op.mapping PLANNED'den {} kalir) — bitiste
        # op.mapping'e YENI nesne (dict(mapping)) atanir; PLANNED'deki {} ile deger
        # farkli oldugundan SQLAlchemy degisikligi algilar. EXECUTING'de bos-sema
        # snapshot'i yazmak ic-ref paylasimi yuzunden deger-esitligini bozardi (M5 tuzağı).
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
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_restore_executor.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -q` → tümü pass.

- [ ] **Step 6: Commit**

```bash
git add src/osbak/restore/executor.py tests/test_restore_executor.py
git commit -m "refactor: RebuildExecutor execute(op, plan) — op ayirmadan yurutur"
```

---


---

## Task 4: RestoreService — iki fazlı plan/apply/show

**Files:**
- Create: `src/osbak/restore/restore_service.py`
- Create: `tests/test_restore_service.py`

**Interfaces:**
- Produces:
  ```python
  class RestorePreflightFailed(Exception):
      def __init__(self, report: ValidationReport) -> None: ...   # SnapshotPreflightFailed deseni

  @dataclass(frozen=True)
  class RestoreApplyResult:
      restore_op_id: int
      state: str
      server_id: str | None

  class RestoreService:
      def __init__(self, session: Any, gateway: OpenstackGateway, restore_gateway_factory: Callable[[], RestoreGateway]) -> None: ...
      def plan(self, restore_point_id: int, options: RestoreOptions, created_by: str | None = None) -> int: ...
      def apply(self, restore_op_id: int, created_by: str | None = None) -> RestoreApplyResult: ...
      def show(self, restore_op_id: int) -> RestoreOp: ...
  ```

**Sözleşme:**
- `plan(restore_point_id, options)`:
  - `session.get(RestorePoint, restore_point_id)` → yoksa `RestorePlanError("restore point yok: <id>")`.
  - `RestorePlanner(point.manifest, options, restore_point_id).build()` → RestorePlan (live/cold → RestorePlanError "henüz desteklenmiyor").
  - `RestoreOp(restore_point_id, strategy=rplan.strategy.value, state="PLANNED", mapping={}, plan=plan_to_dict(rplan), options=options_to_dict(options), created_by=created_by)` → add+commit → `return op.id`.
- `apply(restore_op_id)` (spec §15 reddi + preflight + yürütme):
  1. `session.get(RestoreOp, restore_op_id)` → yoksa `RestorePlanError("restore op yok: <id>")`.
  2. `op.state != "PLANNED"` → `RestorePlanError(f"yeniden plan gerekli (state={op.state})")` — §15: apply reddedilir.
  3. `session.get(RestorePoint, op.restore_point_id)` → YOK → op.state=FAILED, error="restore point silinmis", finished_at, commit, `RestorePlanError("restore point silinmis — yeniden plan")`.
  4. manifest = point.manifest; ctx = `PreflightContext(plan_kind=PlanKind.RESTORE, gateway=self._gateway, instance_uuid=manifest["instance"]["id"], project_id=manifest["project_id"])`; `report = ValidationEngine().validate(PlanKind.RESTORE, ctx)`. FAIL → op.state=FAILED, error="preflight: <name>:<status> listesi", finished_at, commit, `raise RestorePreflightFailed(report)`.
  5. Geçti: `op.state="PREFLIGHT_PASS"; commit`.
  6. `rplan = plan_from_dict(op.plan)`; `mapping = RebuildExecutor(self._restore_gateway_factory(), self._session).execute(op, rplan)` (executor EXECUTING→DONE/FAILED).
  7. `return RestoreApplyResult(restore_op_id=op.id, state=op.state, server_id=mapping.get("server"))`.
- `show(restore_op_id)` → `session.get` → yoksa `RestorePlanError("restore op yok: <id>")`; op döndürür (salt-okunur, gateway yok).
- RestoreService kendi session'a commit eder (SnapshotService deseni: service session'a sahip değil, session parametre olarak gelir — burada constructor session ALIR; CLI session kurar geçer).

**Kayıt için `.preflight.rules` importu:** `restore_service.py` içinde `from osbak.preflight.rules import keystone, restore  # noqa: F401 (register)` — keystone RESTORE'a da uygulanır, restore kuralı register edilir. (Task 2'nin `preflight/rules/restore.py` import'u).

- [ ] **Step 1: Failing test**

`tests/test_restore_service.py`:
```python
import pytest

from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.models import Instance, Project, RestoreOp, RestorePoint
from osbak.restore.model import RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.restore_service import RestorePreflightFailed, RestoreService
from tests.fake_gateway import FakeGateway
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest


def _seed_point(session, manifest, instance_uuid="orig-uuid"):
    # NOT: make_manifest(): instance dict'inde "id" YOK; apply, manifest["instance"]["id"]
    # okur (OrjinalInstanceYok icin) -> test manifestine id enjekte edilir.
    manifest = dict(manifest)
    manifest["instance"] = dict(manifest["instance"])
    manifest["instance"]["id"] = instance_uuid
    proj = Project(keystone_project_id="p-1")
    session.add(proj)
    session.flush()
    inst = Instance(instance_uuid=instance_uuid, project_id=proj.id)
    session.add(inst)
    session.flush()
    point = RestorePoint(kind="snapshot", instance_id=inst.id, manifest=manifest)
    session.add(point)
    session.commit()
    return point


def _empty_gw():
    return FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})


def _service(session, gw=None, mutators=None):
    return RestoreService(
        session,
        gw or _empty_gw(),
        mutators or (lambda: FakeRestoreGateway()),
    )


def test_plan_creates_planned_op(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = session.get(RestoreOp, op_id)
    assert op is not None
    assert op.state == "PLANNED"
    assert op.strategy == "rebuild"
    assert op.plan["strategy"] == "rebuild"
    assert op.plan["steps"][-1]["action"] == "create_server"
    assert op.options == {"strategy": "rebuild", "instance_name": None,
                          "availability_zone": None, "keep_ip": True}


def test_plan_rejects_live_strategy(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    try:
        svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.LIVE))
        assert False
    except RestorePlanError as exc:
        assert "desteklenmiyor" in str(exc)


def test_plan_rejects_missing_point(session) -> None:
    svc = _service(session)
    try:
        svc.plan(999, RestoreOptions(strategy=RestoreStrategy.REBUILD))
        assert False
    except RestorePlanError as exc:
        assert "restore point yok" in str(exc)


def test_apply_executes_to_done(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    mut = FakeRestoreGateway()
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    result = RestoreService(session, _empty_gw(), lambda: mut).apply(op_id)
    assert result.state == "DONE"
    assert result.server_id is not None
    assert len(mut.created["servers"]) == 1
    op = session.get(RestoreOp, op_id)
    assert op.mapping["server"] == result.server_id


def test_apply_preflight_fails_when_original_running(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    gw = FakeGateway(
        projects=[ProjectInfo(id="p-1", name="a")],
        servers={"p-1": [ServerInfo(id="orig-uuid", name="web", project_id="p-1",
                                    status="ACTIVE", flavor_id="f-1")]},
    )
    svc = RestoreService(session, gw, lambda: FakeRestoreGateway())
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    try:
        svc.apply(op_id)
        assert False
    except RestorePreflightFailed as exc:
        assert any(r.name == "orjinal_instance_yok" and not r.passed for r in exc.report.results)
    op = session.get(RestoreOp, op_id)
    assert op.state == "FAILED"
    assert "orjinal_instance_yok" in op.error


def test_apply_rejects_non_planned(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = session.get(RestoreOp, op_id)
    op.state = "DONE"
    session.commit()
    try:
        svc.apply(op_id)
        assert False
    except RestorePlanError as exc:
        assert "yeniden plan" in str(exc)


def test_show_reads_op(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = svc.show(op_id)
    assert op.id == op_id
    assert op.state == "PLANNED"
```

(FakeGateway gerçek imzaları: `projects: list[ProjectInfo]`, `servers: dict[str, list[ServerInfo]]` — `tests/fake_gateway.py`'den. `ServerInfo` zorunlu alanları: id/name/project_id/status/flavor_id.)

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_restore_service.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/restore/restore_service.py`:
```python
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
```

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_restore_service.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -q` → tümü pass.

- [ ] **Step 6: Commit**

```bash
git add src/osbak/restore/restore_service.py tests/test_restore_service.py
git commit -m "feat: RestoreService iki fazli plan/apply/show + preflight baglama"
```

---


---

## Task 5: CLI — `restore plan/apply/show` + NOTES + tam paket

**Files:**
- Modify: `src/osbak/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `src/osbak/restore/NOTES.md`

**CLI sözleşmesi (spec §16'ya CLI aynası):**
- `osbak restore plan <restore_point_id> [--strategy rebuild] [--no-keep-ip] [--name X] [--az Y]` → `RestoreService.plan` → çıktı: `restore_op=<id> state=PLANNED strategy=<strategy> steps=<sayı> resource_delta=<delta>`.
- `osbak restore apply <restore_op_id>` → `RestoreService.apply` → çıktı: `restore_op=<id> state=<DONE|FAILED> server=<server_id | ->`.
- `osbak restore show <restore_op_id>` → `RestoreService.show` → JSON: `{id, state, strategy, error, finished_at, mapping}` (salt-okunur, gateway YOK).
- Strategy seçenek: click.Choice(["rebuild"]) — live/cold KASITLI DIŞI (provider milestone); başka değer → click hata.

**CLI wiring:**
- `_build_connection` (mevcut) + `SDKGateway(conn)` (read) + `_restore_gateway_factory(conn)` — mevcut `_provider_factory` deseni; `cli.py`'de `def _restore_gateway_factory(conn): from osbak.restore.gateway_mutations import SDKRestoreGateway; return SDKRestoreGateway(conn)`.
- Her komut: `settings = ctx.obj`, engine+init_db+session (mevcut desen), `finally: session.close(); engine.dispose()`.
- `restore plan` ve `restore show` gateway gerektirmez (DB-only); `restore apply` connection + SDKGateway + `_restore_gateway_factory` kurar (canlı mutasyon NotImplementedError — provider milestone'a; CLI testleri monkeypatch ile Fake kullanır).

- [ ] **Step 1: Failing test**

`tests/test_cli.py`'ye ekle:
```python
def test_restore_plan_wires_options(monkeypatch, tmp_path) -> None:
    from osbak import cli
    from osbak.restore.model import RestoreOptions, RestoreStrategy

    captured: dict = {}

    class _RestoreStub:
        def __init__(self, session, gateway, factory): ...

        def plan(self, restore_point_id, options, created_by=None):
            captured["rp"] = restore_point_id
            captured["strategy"] = options.strategy
            captured["name"] = options.instance_name
            return 7

    monkeypatch.setattr(cli, "RestoreService", lambda session, gw, f: _RestoreStub(session, gw, f))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n  project_domain_name: default\n  user_domain_name: default\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(cfg), "restore", "plan",
                                  "--name", "web-x", "42"])
    assert result.exit_code == 0
    assert captured["rp"] == 42
    assert captured["strategy"] is RestoreStrategy.REBUILD
    assert captured["name"] == "web-x"
    assert "restore_op=7" in result.output


def test_restore_apply_wires_op_id(monkeypatch, tmp_path) -> None:
    from osbak import cli
    from osbak.restore.restore_service import RestoreApplyResult

    captured: dict = {}

    class _RestoreStub:
        def __init__(self, session, gateway, factory): ...

        def apply(self, restore_op_id, created_by=None):
            captured["op"] = restore_op_id
            return RestoreApplyResult(restore_op_id=1, state="DONE", server_id="s-9")

    monkeypatch.setattr(cli, "RestoreService", lambda session, gw, f: _RestoreStub(session, gw, f))
    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n  project_domain_name: default\n  user_domain_name: default\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(cfg), "restore", "apply", "1"])
    assert result.exit_code == 0
    assert captured["op"] == 1
    assert "state=DONE server=s-9" in result.output


def test_restore_show_prints_op(monkeypatch, tmp_path) -> None:
    from osbak import cli
    from osbak.models import RestoreOp

    class _RestoreStub:
        def __init__(self, session, gateway, factory): ...

        def show(self, restore_op_id):
            return RestoreOp(id=5, restore_point_id=1, strategy="rebuild",
                             state="DONE", mapping={"server": "s-1"})

    monkeypatch.setattr(cli, "RestoreService", lambda session, gw, f: _RestoreStub(session, gw, f))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n  project_domain_name: default\n  user_domain_name: default\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(cfg), "restore", "show", "5"])
    assert result.exit_code == 0
    assert '"state": "DONE"' in result.output
    assert '"server": "s-1"' in result.output
```

- [ ] **Step 2: Run to fail** — `python -m pytest tests/test_cli.py -v` → 3 yeni test FAIL (restore komutu yok).

- [ ] **Step 3: Implement**

`src/osbak/cli.py`'ye ekle (import bloğunu güncelle: `from osbak.restore.model import RestoreOptions, RestoreStrategy` ve `from osbak.restore.restore_service import RestoreService`):
```python
def _restore_gateway_factory(conn):
    from osbak.restore.gateway_mutations import SDKRestoreGateway

    return SDKRestoreGateway(conn)


@main.group()
def restore() -> None:
    """Restore komutlari (iki fazli: plan -> apply)."""


@restore.command("plan")
@click.argument("restore_point_id", type=int)
@click.option("--strategy", type=click.Choice(["rebuild"]), default="rebuild")
@click.option("--no-keep-ip", is_flag=True, default=False)
@click.option("--name", "instance_name", default=None, type=str)
@click.option("--az", "availability_zone", default=None, type=str)
@click.pass_context
def restore_plan(
    ctx: click.Context,
    restore_point_id: int,
    strategy: str,
    no_keep_ip: bool,
    instance_name: str | None,
    availability_zone: str | None,
) -> None:
    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    try:
        options = RestoreOptions(
            strategy=RestoreStrategy(strategy),
            instance_name=instance_name,
            availability_zone=availability_zone,
            keep_ip=not no_keep_ip,
        )
        service = RestoreService(session, None, lambda: None)
        op_id = service.plan(restore_point_id, options)
        plan = session.get(RestoreOp, op_id).plan
        click.echo(
            f"restore_op={op_id} state=PLANNED strategy={strategy} "
            f"steps={len(plan['steps'])} resource_delta={plan['resource_delta']}"
        )
    finally:
        session.close()
        engine.dispose()


@restore.command("apply")
@click.argument("restore_op_id", type=int)
@click.pass_context
def restore_apply(ctx: click.Context, restore_op_id: int) -> None:
    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    conn = _build_connection(settings)
    gateway = SDKGateway(conn)
    try:
        service = RestoreService(session, gateway, lambda: _restore_gateway_factory(conn))
        result = service.apply(restore_op_id)
        server = result.server_id or "-"
        click.echo(f"restore_op={result.restore_op_id} state={result.state} server={server}")
    finally:
        session.close()
        engine.dispose()


@restore.command("show")
@click.argument("restore_op_id", type=int)
@click.pass_context
def restore_show(ctx: click.Context, restore_op_id: int) -> None:
    import json

    settings: Settings = ctx.obj
    engine, session = _make_session(settings)
    try:
        service = RestoreService(session, None, lambda: None)
        op = service.show(restore_op_id)
        click.echo(json.dumps({
            "id": op.id, "state": op.state, "strategy": op.strategy,
            "error": op.error, "finished_at": op.finished_at.isoformat()
            if op.finished_at else None,
            "mapping": op.mapping,
        }, sort_keys=True))
    finally:
        session.close()
        engine.dispose()
```

Ayrıca `cli.py`'ye ortak helper (engine + session döndürür; çağıran `finally`'de ikisini de kapatır):
```python
def _make_session(settings: Settings):
    engine = create_engine_by_url(settings.database.url)
    init_db(engine)
    return engine, make_session_factory(engine)()
```
(Usage: `engine, session = _make_session(settings)`; `finally: session.close(); engine.dispose()` — mevcut komutların `finally: session.close(); engine.dispose()` deseni korunur. NOT: mevcut 3 komutu DEĞİŞTİRME — yeni komutlar helper kullanır; kapsam disiplini.)

- [ ] **Step 4: Run to pass** — `python -m pytest tests/test_cli.py -v` → PASS.

- [ ] **Step 5: NOTES güncelle**

`src/osbak/restore/NOTES.md` derle karma:
```markdown
## Plan 6 (CLI + servis)
- Iki fazli: `RestoreService.plan` RestoreOp(state=PLANNED, plan/options JSONB) yazar;
  `apply` sakli adimlari yurutur. §15: op.state != PLANNED veya restore point silindi -> RestorePlanError("yeniden plan").
- preflight: OrjinalInstanceYok (PlanKind.RESTORE) — orijinal instance live'da mevcut -> FAILED + RestorePreflightFailed.
- executor execute(op, plan) — op'yu kendisi acmaz; EXECUTING->DONE/FAILED. JSON mapping bitiste dict(mapping) yeni nesne.
- CLI: restore plan/apply/show; canli mutasyon SDKRestoreGateway NotImplementedError (provider milestone).
- Model: RestoreOp.plan + options (JSONB) — MEVCUT DB'ye init_db create_all kolon EKLEMEZ; ALTER TABLE RESTORE_OPS ADD COLUMN plan JSON; ADD COLUMN options JSON; gereklidir (yeni kurulumda otomatik).
```

- [ ] **Step 6: Tam paket** — `python -m pytest -q` → tümü pass (baseline 111 + CLI 3 = 114 civarı) → kanıtla-bitti (çıktı göster).

- [ ] **Step 7: Commit**

```bash
git add src/osbak/cli.py tests/test_cli.py src/osbak/restore/NOTES.md
git commit -m "feat: CLI restore plan/apply/show + NOTES"
```

- [ ] **Step 8: Branch kirletmeleri** — temp dosya yok (`git status` temiz).

---

## Doğrulama: plan kendi kendine yeterli mi? (gözden)

- Task 1-5 arası import/imza hizalı: `models.RestoreOp` kolonları (Task 1) → `restore_service` (Task 4) → `executor` (Task 3) → `cli` (Task 5). Task 3 `execute(op, plan)` imzası Task 4'ün `RebuildExecutor(factory(), session).execute(op, rplan)` çağrısıyla birebir.
- `RestoreService(session, gateway, restore_gateway_factory)` — CLI plan/show `None` gateway geçer (DB-only), apply gerçek SDKGateway+factory kurar. Service `self._session`'ı constructorda alır; SQLAlchemy Session tip yok (Any).
- Preflight kaydı: `from osbak.preflight.rules import keystone, restore` — `restore.py` register eder; `keystone_erisim` frozenset(PlanKind) ile RESTORE'da koşar (istenen). `instance_mevcut`/`instance_durum` RESTORE'a uygulanmaz (applies_to: {SNAPSHOT, BACKUP[, ROLLBACK]}) — restore için yalnız `orjinal_instance_yok` + `keystone_erisim` çalışır.
- Fallback kuralı: yalnızca teardown+re-raise except (Task 3, mevcut izinli); `if sid in ...` sesli skip YOK; preflight sessiz alternatif YOK — FAIL → RestorePreflightFailed (deterministik).
- `restore_show` JSON kolon mapping'den salt-okur; `restore show`'da `RestoreOp(...)` stub'ın `mapping` atanmış (constructor) — test stub'da `id/restore_point_id/strategy/state/mapping` verilir, created_at default `_utcnow()` (required) otomatik.
- CLI apply testinde `_build_connection` monkeypatch (gerçek bağlantı yok) — mevcut snapshot-take test deseniyle aynı.
- `_make_session` helper'ı mevcut 3 komutu değiştirmez (sadece yeni komutlar kullanır); kapsam disiplini.
