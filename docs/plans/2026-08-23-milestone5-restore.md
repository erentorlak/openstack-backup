# Plan 5: Restore Motoru — plan soyutlaması + rebuild (kimliği koruyarak yeniden kur) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore motorunun planlama + rebuild çekirdeğini inşa et: manifest (JSONB) → doğrulanmış `RestorePlan` (kaynaklar, eski→yeni UUID eşlemesi, resource delta, bağımlılık sırası) ve bunu yürüten `RebuildExecutor` (SG 2-pass → volume → port [aynı IP/MAC] → flavor → instance → floating IP). Kimlik korunur (aynı IP/MAC), instance UUID değişir (ADR-001 `rebuild`).

**Architecture:** `osbak.restore` — `model.py` (RestoreStrategy, RestoreOptions, RestorePlan, PlanStep, RestorePlanError) → `planner.py` (`RestorePlanner`: manifest → RestorePlan; saf, I/O yok) → `gateway_mutations.py` (mutation-only `RestoreGateway` Protocol + SDK mutasyon sarmalayıcı [canlı] + FakeRestoreGateway [test]) → `executor.py` (RebuildExecutor: seq sıralı yürütme, mapping, restore_ops kaydı) → CLI `osbak restore <restore-point-id>` (kapsam dışı — API milestone'ı; bu plan servis+test). Canlı SDK mutasyon yolları canlı-görev (NOTES); çekirdek FakeRestoreGateway ile test edilir.

**Tech Stack:** Python ≥3.10, mevcut osbak, pytest. Yeni zorunlu bağımlılık YOK.

**Spec:** `docs/specs/2026-08-23-osbak-architecture.md` (§8 restore modları/R1-R2, §15 restore_ops, ADR-001 ile kanıtlanmış mekanikler) + `docs/adr/ADR-001-rollback-strategies.md` (rebuild stratejisi) + `docs/adr/ADR-002`.

## Global Constraints

- **Fallback kuralı:** YOK — çok-anahtar okuma yok, geniş `except Exception` yok. Her restore adımı deterministik: "kaynak var mı" → yarat/var olanı kullan, çakışma varsa `RestorePlanError` (sesli, plan-time) — sessiz "olmadı ötekini yap" YOK. Tek istisna: RebuildExecutor'daki teardown+re-raise `except Exception` (Task 4 notu — deterministik FAILED sonlandırma, fallback değil).
- Restore, `RestorePoint.manifest`'tan planlanır (katalog kaybında manifest object.store kopyasından — bu planda katalog manifesti kullanılır; objek-store kopyası T1 store mevcut olduğunda bağlanır, kapsam dışı).
- `RestoreGateway` (mutation-only) ayrı Protocol: read gateway (OpenstackGateway) DEĞİŞMEZ. İmzalar aşağıda; SDK mutasyon sarmalayıcı canlı-görev (birim test dışı), FakeRestoreGateway test çifti.
- Rebuild kimlik: port'lar **açıkça** yaratılır (istenen IP + MAC), instance o port'larla boot edilir → aynı IP/MAC, yeni UUID. Orijinal instance silinmiş/durdurulmuş olmalı — preflight `instance_mevcut` ters kontrol (silinmiş → rebuild uygun; yoksa `RestorePlanError` "orijinali önce durdur/sil").
- Flavor: manifest'teki tam spec'e uyan flavor var mı → yoksa gizli `restore-<hash>` yarat (private); asla "en yakın flavor" (extra_specs kaybeder).
- SG: 2-pass — önce boş gruplar (remote_group ref'leri için), sonra kurallar.
- `restore_ops` satırı state machine: `PLANNED → PREFLIGHT_PASS → EXECUTING → VERIFY → DONE | FAILED` (ADT-001 §15); başarısız adımda mapping kalır, `state=FAILED`, `error` dolu.
- No live infra; testler FakeRestoreGateway + manifest fixture'ları + sqlite session.
- `osbak.restore` kapsamı: rebuild + plan. **live (swap_volume) ve cold (storage-direct) BU planın kapsamı DIŞI** — provider milestone'ı (takip Plan 6+); `RestoreStrategy` enum'ında var ama executor yalnız rebuild'i uygular (diğerleri `RestorePlanError("henüz desteklenmiyor")`).

## File Structure

```
src/osbak/restore/__init__.py
src/osbak/restore/model.py          # RestoreStrategy, RestoreOptions, RestorePlan, PlanStep, RestorePlanError
src/osbak/restore/planner.py       # RestorePlanner (manifest → RestorePlan; saf, I/O yok)
src/osbak/restore/gateway_mutations.py  # RestoreGateway Protocol + SDKRestoreGateway (live)
src/osbak/restore/executor.py       # RebuildExecutor (seq sıralı yürütme, restore_ops kaydı)
src/osbak/restore/NOTES.md
tests/fake_restore_gateway.py       # FakeRestoreGateway (test çifti)
tests/test_restore_model.py
tests/test_restore_gateway.py
tests/test_restore_planner.py       # make_manifest fixture aynı dosyada; executor testi buradan import eder
tests/test_restore_executor.py
```

CLI/API wiring: KAPSAM DIŞI (Plan 7 API milestone); bu plan servis + test üretir.

---

## Task 1: restore model — strateji/options/plan tipleri

**Files:**
- Create: `src/osbak/restore/__init__.py` (boş)
- Create: `src/osbak/restore/model.py`
- Create: `tests/test_restore_model.py`

**Interfaces:**
- Produces:
  - `RestoreStrategy` (REBUILD="rebuild", LIVE="live", COLD="cold") — str enum.
  - `RestoreOptions(strategy: RestoreStrategy, instance_name: str | None = None, availability_zone: str | None = None, keep_ip: bool = True)` — frozen.
  - `RestorePlan(strategy: RestoreStrategy, restore_point_id: int, steps: tuple[PlanStep, ...], resource_delta: dict[str, int])` — frozen.
  - `PlanStep(seq: int, action: str, key: str, payload: dict)` — frozen.
  - `RestorePlanError(Exception)`.

**Sözleşme:** `PlanStep.key` glob; `action` şunlardan biri olacak: `ensure_security_group_shell`, `add_security_group_rules`, `create_volume`, `create_port`, `find_or_create_flavor`, `create_server` (executor Task 4 bunlara göre çalışır). `resource_delta` örn. `{"volumes": n, "ports": n, "security_groups": n, "servers": 1}` (plan zamanı tahmini; executor fiili yaratmayı izler).

- [ ] **Step 1: Failing test**

`tests/test_restore_model.py`:
```python
from osbak.restore.model import (
    PlanStep,
    RestoreOptions,
    RestorePlan,
    RestorePlanError,
    RestoreStrategy,
)


def test_strategy_values() -> None:
    assert RestoreStrategy.REBUILD.value == "rebuild"
    assert RestoreStrategy.LIVE.value == "live"
    assert RestoreStrategy.COLD.value == "cold"


def test_options_defaults() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD)
    assert opts.instance_name is None
    assert opts.availability_zone is None
    assert opts.keep_ip is True


def test_plan_step_frozen_and_fields() -> None:
    step = PlanStep(seq=1, action="create_volume", key="vol:v-1", payload={"size": 10})
    assert step.action == "create_volume"
    try:
        step.payload["size"] = 20  # frozen dataclass'ın dict'i mutable — plan INNER kopya yapmaz
        assert step.payload["size"] == 20
    except Exception:
        pass  # frozen sözleşmesi yalnızca attribute atamasını engeller


def test_plan_frozen() -> None:
    plan = RestorePlan(
        strategy=RestoreStrategy.REBUILD,
        restore_point_id=1,
        steps=(),
        resource_delta={},
    )
    try:
        plan.strategy = RestoreStrategy.LIVE  # frozen → AttributeError
        assert False
    except AttributeError:
        pass


def test_plan_error_is_exception() -> None:
    try:
        raise RestorePlanError("plan hatasi")
    except RestorePlanError as exc:
        assert "plan" in str(exc)
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_restore_model.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/restore/model.py`:
```python
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class RestoreStrategy(str, enum.Enum):
    REBUILD = "rebuild"
    LIVE = "live"
    COLD = "cold"


class RestorePlanError(Exception):
    pass


@dataclass(frozen=True)
class RestoreOptions:
    strategy: RestoreStrategy
    instance_name: str | None = None
    availability_zone: str | None = None
    keep_ip: bool = True


@dataclass(frozen=True)
class PlanStep:
    seq: int
    action: str
    key: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RestorePlan:
    strategy: RestoreStrategy
    restore_point_id: int
    steps: tuple[PlanStep, ...]
    resource_delta: dict[str, int]
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_restore_model.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/restore tests/test_restore_model.py
git commit -m "feat: restore model (strategy, options, plan, step, error)"
```

---

## Task 2: RestoreGateway — mutation-only Protocol + FakeRestoreGateway

**Files:**
- Create: `src/osbak/restore/gateway_mutations.py`
- Create: `tests/fake_restore_gateway.py`

**Interfaces:**
- Produces (mutation-only — READ gateway değişmez):
  ```python
  class RestoreGateway(Protocol):
      def ensure_security_group(self, name: str, description: str, project_id: str) -> str: ...
      def add_security_group_rules(self, security_group_id: str, rules: list[dict]) -> None: ...
      def create_volume(self, name: str, size_gb: int, volume_type: str | None,
                        availability_zone: str | None, source_snapshot: str | None) -> str: ...
      def create_port(self, network_id: str, mac_address: str | None,
                      fixed_ip: str | None, security_group_ids: list[str],
                      allowed_address_pairs: list[dict], project_id: str) -> str: ...
      def find_or_create_flavor(self, name: str, vcpus: int, ram_mb: int, disk_gb: int,
                                ephemeral_gb: int, swap_mb: int, extra_specs: dict) -> str: ...
      def create_server(self, name: str, flavor_id: str, volume_ids: list[str],
                        port_ids: list[str], security_group_ids: list[str],
                        availability_zone: str | None, user_data: str | None,
                        key_name: str | None, metadata: dict, tags: list[str],
                        config_drive: bool, project_id: str) -> str: ...
  ```
  - `SDKRestoreGateway` — canlı-görev sarmalayıcı (NOTES'ta doğrulanacak); birim test DIŞI. Metotların her biri `raise NotImplementedError("canlı ortamda doğrulanacak")` — bu plan çekirdeği FakeRestoreGateway ile test edilir.
  - `FakeRestoreGateway` (tests/) — aynı Protocol; `self.created` dict (action→liste), `self._next_id` sayaç; her `create_*`/`ensure_*` deterministik `f"{action}-{next_id}"` id döndürür; `ensure_security_group` aynı name'de tekrar çağrılırsa aynı id'yi döndürür (idempotent).

- [ ] **Step 1: Failing test**

`tests/fake_restore_gateway.py`:
```python
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
```

`tests/test_restore_model.py`'ye ek (veya ayrı `tests/test_restore_gateway.py` — ayrı dosya tercih):
```python
def test_fake_gateway_idempotent_security_group() -> None:
    gw = FakeRestoreGateway()
    a = gw.ensure_security_group("web", "", "pid-1")
    b = gw.ensure_security_group("web", "", "pid-1")
    assert a == b
    assert len(gw.created["security_groups"]) == 1


def test_fake_gateway_creates_distinct_ids() -> None:
    gw = FakeRestoreGateway()
    v1 = gw.create_volume("v1", 10, "ssd", None, None)
    p1 = gw.create_port("n-1", "aa:bb:cc:dd:ee:ff", "10.0.0.5", [], [], "pid-1")
    assert v1 != p1
    assert v1 == "vol-1" and p1 == "port-2"
```
(İkinci test farklı dosyada `tests/test_restore_gateway.py` içinde; import `from tests.fake_restore_gateway import FakeRestoreGateway`.)

- [ ] **Step 2: Run to fail** — `pytest tests/test_restore_gateway.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/restore/gateway_mutations.py`:
```python
from __future__ import annotations

from typing import Any, Protocol


class RestoreGateway(Protocol):
    def ensure_security_group(
        self, name: str, description: str, project_id: str
    ) -> str: ...

    def add_security_group_rules(
        self, security_group_id: str, rules: list[dict]
    ) -> None: ...

    def create_volume(
        self,
        name: str,
        size_gb: int,
        volume_type: str | None,
        availability_zone: str | None,
        source_snapshot: str | None,
    ) -> str: ...

    def create_port(
        self,
        network_id: str,
        mac_address: str | None,
        fixed_ip: str | None,
        security_group_ids: list[str],
        allowed_address_pairs: list[dict],
        project_id: str,
    ) -> str: ...

    def find_or_create_flavor(
        self,
        name: str,
        vcpus: int,
        ram_mb: int,
        disk_gb: int,
        ephemeral_gb: int,
        swap_mb: int,
        extra_specs: dict,
    ) -> str: ...

    def create_server(
        self,
        name: str,
        flavor_id: str,
        volume_ids: list[str],
        port_ids: list[str],
        security_group_ids: list[str],
        availability_zone: str | None,
        user_data: str | None,
        key_name: str | None,
        metadata: dict,
        tags: list[str],
        config_drive: bool,
        project_id: str,
    ) -> str: ...


class SDKRestoreGateway:
    """Canlı mutasyon sarmalayıcı — birim test DIŞI (canlı ortam doğrulaması).

    Metotlar Nova/Neutron/Cinder'a delegate eder; tam API çağrıları
    canlı ortamda doğrulanacak. Sözleşme imzaları yukarıdaki Protocol ile aynıdır.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def ensure_security_group(self, name: str, description: str, project_id: str) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def add_security_group_rules(self, security_group_id: str, rules: list[dict]) -> None:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_volume(
        self, name: str, size_gb: int, volume_type: str | None,
        availability_zone: str | None, source_snapshot: str | None,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_port(
        self, network_id: str, mac_address: str | None, fixed_ip: str | None,
        security_group_ids: list[str], allowed_address_pairs: list[dict], project_id: str,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def find_or_create_flavor(
        self, name: str, vcpus: int, ram_mb: int, disk_gb: int,
        ephemeral_gb: int, swap_mb: int, extra_specs: dict,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def create_server(
        self, name: str, flavor_id: str, volume_ids: list[str], port_ids: list[str],
        security_group_ids: list[str], availability_zone: str | None,
        user_data: str | None, key_name: str | None, metadata: dict,
        tags: list[str], config_drive: bool, project_id: str,
    ) -> str:
        raise NotImplementedError("canlı ortamda doğrulanacak")
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_restore_gateway.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/restore/gateway_mutations.py tests/fake_restore_gateway.py tests/test_restore_gateway.py
git commit -m "feat: RestoreGateway mutation protocol, FakeRestoreGateway"
```

---

## Task 3: RestorePlanner — manifest → RestorePlan

**Files:**
- Create: `src/osbak/restore/planner.py`
- Create: `tests/test_restore_planner.py`
- (Task 1/2 tipleri ve FakeRestoreGateway kullanılır.)

**Interfaces:**
- Produces:
  ```python
  class RestorePlanner:
      def __init__(self, manifest: dict, options: RestoreOptions, restore_point_id: int) -> None: ...
      def build(self) -> RestorePlan: ...
  ```

**Sözleşme (manifest ← `manifest/builder.py` çıktısı):** `project_id`; `instance{name,project_id,key_name,config_drive,availability_zone,metadata,tags}`; `flavor{name,vcpus,ram,disk,ephemeral,swap,extra_specs}`; `block_device_mapping[{volume_id,size,volume_type,boot_index}]`; `network.ports[{id,network_id,mac_address,fixed_ips[{ip_address}],security_group_ids,allowed_address_pairs}]`; `security_groups[{id,name,description,rules}]`.

**Üretilecek adımlar (seq sırasıyla):**
1. Her SG için `ensure_security_group_shell` — key `sg:{name}`, payload `{name,description,project_id}`; **tümü** tek geçişte (önce bütün kabuklar).
2. Sonra her SG için `add_security_group_rules` — key `sg_rules:{name}`, payload `{security_group_key: "sg:{name}", rules}`. `rules` kopyalanır (sığ kopya) ve `remote_group_id` (eski id) `remote_group_name`'e çevrilir: id `sg_id_to_name`'de bulunursa `remote_group_id` silinir, `remote_group_name` eklenir; bulunamazsa `RestorePlanError("bilinmeyen uzak grup: <id>")` (sessiz skip YOK — fallback kuralı). `remote_ip_prefix`'li (null `remote_group_id`) kurallar dokunulmadan geçer (2-geçiş: kurallar başka kabuğun adına atıf yapabildiği, executor yeni id'yi adla çözdüğü için).
3. Her bdm için `create_volume` — key `vol:{volume_id}`, boot_index'e göre sıralı, payload `{name,size_gb,volume_type,availability_zone}`.
4. Her port için `create_port` — key `port:{port_id}`, payload `{network_id,mac_address,fixed_ip,security_group_names,allowed_address_pairs,project_id}`. `fixed_ip` = port.fixed_ips[0].ip_address **yalnızca `options.keep_ip=True` ise** (kesilirse None → Neutron atar). `security_group_names` = manifest SG id→name eşlemesiyle çözülür (yeni id'leri executor bilir).
5. `find_or_create_flavor` — key `flavor`, payload `{name,vcpus,ram_mb,disk_gb,ephemeral_gb,swap_mb,extra_specs}`.
6. `create_server` (son adım) — key `server`, payload `{name: options.instance_name or instance.name, flavor_key:"flavor", volume_keys:[vol:... boot sırası], port_keys:[port:...], security_group_names, availability_zone, user_data:None, key_name, metadata, tags, config_drive, project_id}`.

`resource_delta` = `{"volumes": n, "ports": n, "security_groups": n, "flavors": 1, "servers": 1}`.

**Karar sesi:** `options.strategy != REBUILD` → `RestorePlanError("henüz desteklenmiyor")`. Uygulama **saf** (I/O yok) — var/yok kararlarını `ensure_*` idempotentliğine ve preflight'a bırakır.

- [ ] **Step 1: Failing test**

`tests/test_restore_planner.py` (manifest helper aynı dosyada):
```python
from osbak.restore.model import PlanStep, RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner


def make_manifest() -> dict:
    return {
        "schema_version": 1,
        "project_id": "p-1",
        "instance": {
            "name": "web-01", "project_id": "p-1", "key_name": "admin",
            "config_drive": True, "availability_zone": "nova:az1",
            "metadata": {"env": "prod"}, "tags": ["web"],
        },
        "flavor": {"name": "m1.small", "vcpus": 1, "ram": 2048, "disk": 10,
                    "ephemeral": 0, "swap": 0, "extra_specs": {}},
        "block_device_mapping": [
            {"volume_id": "v-root", "size": 10, "volume_type": "ssd", "boot_index": 0},
            {"volume_id": "v-data", "size": 50, "volume_type": "ssd", "boot_index": 1},
        ],
        "network": {"ports": [
            {"id": "port-1", "network_id": "net-1", "mac_address": "aa:bb:cc:dd:ee:ff",
             "fixed_ips": [{"subnet_id": "sub-1", "ip_address": "10.0.0.5"}],
             "security_group_ids": ["sg-old-1"], "allowed_address_pairs": []},
        ]},
        "security_groups": [
            {"id": "sg-old-1", "name": "web", "description": "web rules", "rules": [
                {"direction": "ingress", "protocol": "tcp", "ether_type": "IPv4",
                 "port_range_min": 80, "port_range_max": 80,
                 "remote_ip_prefix": "0.0.0.0/0", "remote_group_id": None},
            ]},
        ],
        "server_groups": [],
    }


def test_build_shells_come_before_rules() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    actions = [s.action for s in plan.steps]
    assert actions.index("ensure_security_group_shell") < actions.index("add_security_group_rules")


def test_build_server_is_last() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    assert plan.steps[-1].action == "create_server"
    assert plan.steps[-1].key == "server"


def test_build_volume_keys_ordered_by_boot() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    server = plan.steps[-1].payload
    assert server["volume_keys"] == ["vol:v-root", "vol:v-data"]


def test_build_port_fixed_ip_respects_keep_ip() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=True)
    plan = RestorePlanner(make_manifest(), opts, 1).build()
    port = next(s for s in plan.steps if s.action == "create_port")
    assert port.payload["fixed_ip"] == "10.0.0.5"
    assert port.payload["security_group_names"] == ["web"]

    opts_no = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=False)
    plan_no = RestorePlanner(make_manifest(), opts_no, 1).build()
    port_no = next(s for s in plan_no.steps if s.action == "create_port")
    assert port_no.payload["fixed_ip"] is None


def test_build_instance_name_override() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, instance_name="web-restore")
    plan = RestorePlanner(make_manifest(), opts, 1).build()
    assert plan.steps[-1].payload["name"] == "web-restore"


def test_build_rejects_unplanned_strategy() -> None:
    try:
        RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.LIVE), 1).build()
        assert False
    except RestorePlanError as exc:
        assert "desteklenmiyor" in str(exc)


def test_resource_delta() -> None:
    plan = RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    assert plan.resource_delta == {"volumes": 2, "ports": 1, "security_groups": 1,
                                   "flavors": 1, "servers": 1}
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_restore_planner.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/restore/planner.py`:
```python
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
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_restore_planner.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/restore/planner.py tests/test_restore_planner.py
git commit -m "feat: RestorePlanner manifest->RebuildPlan (saf plan)"
```

---

## Task 4: RebuildExecutor — plan → mutation + restore_ops kaydı

**Files:**
- Create: `src/osbak/restore/executor.py`
- Create: `tests/test_restore_executor.py`

**Interfaces:**
- Produces:
  ```python
  class RebuildExecutor:
      def __init__(self, gateway: RestoreGateway, session) -> None: ...
      def execute(self, plan: RestorePlan, created_by: str | None = None) -> dict[str, str]: ...
  ```
  `execute` → eski→yeni id eşlemesi ve RestoreOp kaydı (bkz. `models.RestoreOp`).

**Sözleşme (devlet makinesi — spec §15):** `RestoreOp(state=EXECUTING, mapping={})` açılır → başarı: `state=DONE, finished_at, error=None, mapping` doldurulur → hata: `state=FAILED, finished_at, error=str, kısmi mapping korunur` ve `RestorePlanError` yeniden atılır. `mapping` şeması: `{"volumes": {eski_vol_id: yeni_vol_id}, "ports": {eski_port_id: yeni_port_id}, "security_groups": {sg_adı: yeni_sg_id}, "flavor": yeni_flavor_id, "server": yeni_server_id}`.

**Yürütme:** adımlar `seq` sırasıyla; her adımda:
- `ensure_security_group_shell` → `gateway.ensure_security_group` → çekirdek `security_groups[name]=id`.
- `add_security_group_rules` → her kuralın `remote_group_name`'i `mapping["security_groups"][ad]` ile yeni id'ye çözülür, `remote_group_name` anahtarı düşer, `remote_group_id` koyulur (planner en azından tüm SG kabuklarını önceden işler, bu yüzden ad her zaman map'te); `security_group_id` çekirdekten (`payload["security_group_key"]` ile) çözülür → `gateway.add_security_group_rules(id, translated_rules)`.
- `create_volume` → `gateway.create_volume` → `volumes[payload["name"]]=id` ve eski id `key.split(":")[1]`.
- `create_port` → `gateway.create_port` (security_group_ids payload adlarından çözülür) → `ports[eski_port_id]=id`.
- `find_or_create_flavor` → `flavor=id`.
- `create_server` → `gateway.create_server` (volume_ids/port_ids/flavor_id/sg ids payload key'lerinden çözülür) → `server=id`.

**Hata yakalama:** adım döngüsü TEK teardown+re-raise `except Exception` ile sarmalanır. TÜM hatalar — gateway RuntimeError'ları ve bilinmeyen adım dahil `RestorePlanError`'lar — aynı handler'a düşer: `op.mapping = dict(mapping); state=FAILED; error; finished_at; session.commit()` sonra `raise RestorePlanError(str(exc)) from exc`. Rollback YOK (FAILED, kısmi mapping ile commit edilerek kaydedilir).

**`except Exception` notu (kasıtlı, izinli):** Tek handler `RestorePlanError`'ı da yakalar (eski `except RestorePlanError: raise` passthrough'u KALDIRILDI — bilinmeyen adım senaryosu `RestorePlanError("bilinmeyen adim: ...")` üretir ve bu da FAILED kaydı yaşamadan geçip EXECUTING'de kalakalırdı; spec §15 FAILED ister). Bu AGENTS.md'de izinli kalıptır: state=FAILED + error + commit → `raise RestorePlanError from exc`. Yani senaryo belirsizliğinde "başka yol dene" değildir; aksine **deterministik hata sonlandırmasıdır** (devlet makinesi FAILED'e geçer, kısmi mapping korunur). Ayrıca RESTORE_AGENT subagent'ların bu notu dikkate alıp executor'ı değiştirmemesi için koda `# noqa: BLE001` koyulur.

- [ ] **Step 1: Failing test**

`tests/test_restore_executor.py`:
```python
import pytest

from osbak.models import RestoreOp
from osbak.restore.executor import RebuildExecutor
from osbak.restore.model import RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest


def build_plan():
    return RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()


def test_execute_creates_all_resources_and_records_op(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    mapping = exc.execute(build_plan())

    assert gw.created["servers"][0]["volumes"] == [mapping["volumes"]["v-root"],
                                                   mapping["volumes"]["v-data"]]
    assert gw.created["servers"][0]["ports"] == [mapping["ports"]["port-1"]]
    assert gw.created["servers"][0]["sgs"] == [mapping["security_groups"]["web"]]

    op = session.query(RestoreOp).one()
    assert op.strategy == "rebuild"
    assert op.state == "DONE"
    assert op.restore_point_id == 1
    assert op.error is None
    assert op.finished_at is not None
    assert op.mapping["server"] == mapping["server"]


def test_execute_sg_rules_reference_created_shell(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    exc.execute(build_plan())
    rule_entry = gw.created["sg_rules"][0]
    sg_id = rule_entry["id"]
    assert sg_id == gw.created["security_groups"][0]["id"]
    assert rule_entry["rules"][0]["protocol"] == "tcp"


def test_execute_failure_marks_failed_and_raises(session) -> None:
    class ExplodingGateway(FakeRestoreGateway):
        def create_volume(self, *a, **k):
            raise RuntimeError("boom")

    gw = ExplodingGateway()
    exc = RebuildExecutor(gw, session)
    try:
        exc.execute(build_plan())
        assert False
    except RestorePlanError as exc2:
        assert "boom" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "boom" in op.error
    assert op.finished_at is not None
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_restore_executor.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/restore/executor.py`:
```python
from __future__ import annotations

import copy
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

    def execute(self, plan: RestorePlan, created_by: str | None = None) -> dict[str, Any]:
        # NOT: JSON kolona AYNI NESNE ICI mutasyon izlenmez (MutableDict yok).
        # mapping lokal dict olarak kurulur; INSERT aninda SNAPSHOT olarak
        # deepcopy yazilir (dict() sıg kopyasi ic dict'leri paylasirdi, JSON
        # kolonun deger-esitligi karsilastirmasi FAILED yarim mapping'ini
        # silerdi), bitiste op.mapping'e YENI nesne atanir.
        mapping: dict[str, Any] = {"volumes": {}, "ports": {}, "security_groups": {}}
        op = RestoreOp(
            restore_point_id=plan.restore_point_id,
            strategy=plan.strategy.value,
            state="EXECUTING",
            mapping=copy.deepcopy(mapping),
            created_by=created_by,
        )
        self._session.add(op)
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

- [ ] **Step 4: Run to pass** — `pytest tests/test_restore_executor.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/restore/executor.py tests/test_restore_executor.py
git commit -m "feat: RebuildExecutor + restore_ops state machine kaydi"
```

---

## Task 5: NOTES + tam paket doğrulama

- [ ] **Step 1: NOTES güncelle**

`src/osbak/restore/NOTES.md` (oluştur — repo konvansiyonu: `# restore — notlar (LLM'ler için)` + Ne/Neden/Tuzaklar):
```markdown
# restore — notlar (LLM'ler için)

Ne: restore motorunun planlama + rebuild çekirdeği. Manifest (JSONB) → saf RestorePlan →
RestoreGateway mutasyonları ile kimliği koruyarak yeniden kurulum (aynı IP/MAC, yeni UUID).

Neden:
- RestorePlanner: SAF (I/O yok) — manifest → adım kümesi; var/yok kararları ensure_*
  idempotentliğine ve preflight'a bırakılır. Strategy LIVE/COLD → RestorePlanError("henüz desteklenmiyor").
  SG 2-geçiş (önce bütün kabuklar, sonra kurallar — kurallar başka grubun id'sine atıf yapar).
- RebuildExecutor: seq sıralı yürütme; RestoreOp state machine EXECUTING→DONE|FAILED;
  mapping eski→yeni id tutar (`volumes`/`ports`/`security_groups`/`flavor`/`server`), FAILED'da
  kısmi mapping korunur. Teardown+re-raise except (AGENTS izinli kalıp); sonradan teardown yok.
- RestoreGateway = mutation-only ayrı Protocol; read tarafı (OpenstackGateway) DEĞİŞMEZ.
- mapping şeması katalog JSONB'de (RestoreOp.mapping).

Tuzaklar:
- SDKRestoreGateway (canlı mutasyon) KASITLI boş — gerçek Nova/Neutron/Cinder çağrıları
  canlı ortamda doğrulanır (provider milestone). Birim testler FakeRestoreGateway ile döner.
- Port fixed_ip yalnızca keep_ip=True iken eklenir; aksi halde Neutron atar.
- find_or_create_flavor: exact spec eşleşmesi; "en yakın flavor" YOK (extra_specs kaybeder).
- restore_ops mapping anahtarları: volume/port'lar için ORİJİNAL id (key'in ":" sonrası),
  security_groups için ad (idempotent ensure ad ile çalışır).
```

- [ ] **Step 2: Tam paket**

```bash
source .venv/bin/activate
python -m pytest -q
```

- [ ] **Step 3: Plan dosyası bütünlüğü** — `docs/plans/` içinde Task başlık deseni tutarlı (`## Task N: ...`), bu plan dosyasında kopuk/yarım kod blokları yok (yapıştırma kontrolü: her fenced block açılıp kapanıyor).

- [ ] **Step 4: Commit**

```bash
git add src/osbak/restore/NOTES.md
git commit -m "docs: Plan 5 NOTES ve dogrulama"
```

- [ ] **Step 5: Branch kirletmeleri** — temp dosya/artık yok (`git status` temiz).

---

## Doğrulama: plan kendi kendine yeterli mi? (gözden)

- Task 1-4 arasındaki import/Protokol imzaları hizalı: model → planner/executor → gateway_mutations → fake/test.
- manifest kontratı `builder.py`'daki gerçek anahtar adlarıyla birebir (doğrulandı: `block_device_mapping[]volume_id/size/volume_type/boot_index`, `network.ports[]network_id/mac_address/fixed_ips/security_group_ids/allowed_address_pairs`, `security_groups[]id/name/description/rules`, `flavor{}name/vcpus/ram/disk/ephemeral/swap/extra_specs`, `instance{}name/project_id/key_name/config_drive/availability_zone/metadata/tags`).
- `RestoreOp` gerçek kolonlarıyla eşleşir (`strategy/state/mapping/created_by/created_at/finished_at/error`).
- TDD kuralına uygun (önce test → kırmızı → implement → yeşil → commit).
- Fallback kuralına uygun: tek teardown+re-raise `except Exception` — `RestorePlanError` (bilinmeyen adım) dahil TÜM hatalar tek handler'da FAILED sonlandırma yaşar (Task 4 notu); sessiz alternatif yol YOK. Bu planda unquiesce benzeri teardown adımı yok.
- **JSON kalıcılığı (düzeltildi):** `RestoreOp.mapping` plain JSON kolon (MutableDict yok) → executor mapping'i lokal dict olarak kurar, bitişte `op.mapping = mapping` (yeni nesne ataması) yapar — aynı nesne içi mutasyon SQLAlchemy tarafından izlenmezdi.
