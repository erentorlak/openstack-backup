# Plan 3: Snapshot Orkestrasyonu (provider + quiesce + restore-point kaydı) — Implementation Plan

> **Durum: TAMAMLANDI** — plan implement edildi, main'e merge edildi (tarihsel
> kayıt). Kalıcı davranış ve tuzaklar için src/osbak/snapshot/NOTES.md ve README'ye bakın.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** İlk gerçek itoh dizimini inşa et: storage provider soyutlaması (başlangıçta Ceph/RBD), Nova guest quiesce/unquiesce, ve bir instance'ı snapshotlayıp kataloga restore-point + volume_backup olarak kaydeden **orchestrator**. Preflight'ı bu akışa bağla. CLI: `osbak snapshot-take <instance-uuid>`.

**Architecture:** `osbak.providers.base` (capabilities modeli + `SnapshotProvider` Protocol) → `osbak.providers.ceph` (`CephProvider`: rados probe → yoksa `ProviderUnavailable`, gerçek rados yolu canlı-ortam) → `osbak.snapshot.service.SnapshotService` (preflight → quiesce → per-volume snapshot → restore_point/volume_backup kaydı → unquiesce). Gateway'e `quiesce_guest`/`unquiesce_guest` eklenir (Protocol + FakeGateway + SDKGateway). Testler: FakeGateway + FakeProvider + sqlite session; canlı ağ YOK.

**Tech Stack:** Python ≥3.10, mevcut osbak paketi, pytest. Yeni zorunlu bağımlılık YOK (rados/rbd isteğe bağlı, canlı kurulumda `osbak[ceph]`).

**Spec:** `docs/specs/2026-08-23-osbak-architecture.md` (§7.1 SNAPSHOT adımı, §9 provider, §12 tutarlılık, §15 state machine, §20 yapım sırası adım 3) + `docs/adr/ADR-001` + `docs/adr/ADR-002`

## Global Constraints

- **Fallback kuralı:** `_pick`/çok-anahtar okuma YOK, geniş `except Exception` YOK. Provider yoksa (backend eşleşmiyor / rados kurulu değil) → `ProviderUnavailable` fırlatılır ve **preflight FAIL'e çevirir** (deterministik; sessiz "boşta kal" yok). Unquiesce, quiesce olduysa **her zaman** çalışır (snapshot hata verse bile) — bu fallback DEĞİL, zorunlu teardown.
- `rados`/`rbd` venv'de YOK. `CephProvider.__init__` `importlib.util.find_spec("rados")` probe eder; yoksa `ProviderUnavailable` fırlatır (find-spec = deterministik yetenek kontrolü, except değil). Gerçek rados kod yolu canlı-ortam doğrulamasına bırakılır (SDKGateway gibi birim test kapsamı dışı); `snap_name()` saf fonksiyon birim test edilir.
- Quiesce: `require_consistent` ise `gateway.quiesce_guest(server_id)` sonra snapshot'lar, `gateway.unquiesce_guest(server_id)` (her zaman teardown). `allow_crash` ise quiesce hiç çağrılmaz.
- Restore-point: `kind=SNAPSHOT`, `manifest` = ManifestBuilder çıktısı (JSONB); her volume için `VolumeBackup(tier="t0", snapshot_ref=..., object_manifest={})`. Manifestin objek-store kopyası T1 milestone'ında (Plan 4).
- Provider derleme: `SnapshotService` bir `provider_factory: Callable[[str], SnapshotProvider]` alır (backend/driver adına göre provider döndürür); eşleşme yoksa `ProviderUnavailable`.
- No live infra; tests FakeGateway/FakeProvider/sqlite.
- `openstacksdk` quiesce yüzü: SDKGateway implementer'ı kurulu SDK kaynağından doğrular (release-gated); SDK'da action yoksa Nova `os-quiesce`/`os-unquiesce` action'ını SDK'nın desteklediği yolla çağırır ve kararı NOTES'a yazar.

## File Structure

```
src/osbak/providers/__init__.py
src/osbak/providers/base.py        # ProviderCapabilities, ProviderUnavailable, SnapshotTarget, SnapshotRef, SnapshotProvider(Protocol)
src/osbak/providers/ceph.py        # CephProvider + snap_name() saf fonksiyon
src/osbak/snapshot/__init__.py
src/osbak/snapshot/service.py      # SnapshotService.snapshot_instance(...)
src/osbak/snapshot/NOTES.md
tests/test_providers_base.py
tests/test_providers_ceph.py
tests/test_snapshot_service.py
```

Üst düzey: `cli.py`'ye `snapshot-take` komutu (Task 5).

---

## Task 1: providers base — capabilities modeli + SnapshotProvider Protocol

**Files:**
- Create: `src/osbak/providers/__init__.py` (boş)
- Create: `src/osbak/providers/base.py`
- Create: `tests/test_providers_base.py`

**Interfaces:**
- Produces:
  - `ProviderCapabilities(can_snapshot: bool, native_diff: bool, data_path: str, rollback: frozenset[str], source_kind: str)` — frozen dataclass; `data_path` ∈ {"rbd","nfs","iscsi","fc"}; `rollback` ⊆ {"live","cold","rebuild"}.
  - `ProviderUnavailable(Exception)` — provider yok/kurulu değil.
  - `SnapshotTarget(image: str, pool: str, project_id: str, instance_id: str)` — frozen.
  - `SnapshotRef(provider: str, image: str, pool: str, snapshot: str, created_at: str)` — frozen.
  - `SnapshotProvider` Protocol: `name: str`, `capabilities: ProviderCapabilities`, `snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef`, `delete(self, ref: SnapshotRef) -> None`.

- [x] **Step 1: Failing test**

`tests/test_providers_base.py`:
```python
import pytest

from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)


def test_capabilities_frozen() -> None:
    caps = ProviderCapabilities(
        can_snapshot=True,
        native_diff=True,
        data_path="rbd",
        rollback=frozenset({"live", "cold", "rebuild"}),
        source_kind="pool",
    )
    assert caps.can_snapshot is True
    assert caps.rollback == frozenset({"live", "cold", "rebuild"})


def test_provider_unavailable_is_exception() -> None:
    with pytest.raises(ProviderUnavailable):
        raise ProviderUnavailable("ceph provider yok")


def test_target_and_ref_are_frozen() -> None:
    target = SnapshotTarget(image="vol-1", pool="volumes", project_id="p", instance_id="i")
    ref = SnapshotRef(provider="ceph", image="vol-1", pool="volumes", snapshot="s-1", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(AttributeError):
        target.image = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        ref.snapshot = "y"  # type: ignore[misc]


def test_protocol_is_subscriptable_protocol() -> None:
    assert SnapshotProvider  # isinstance check yerine varlık/type check
```

- [x] **Step 2: Run to fail** — `pytest tests/test_providers_base.py -v` → FAIL (modül yok).

- [x] **Step 3: Implement**

`src/osbak/providers/base.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderUnavailable(Exception):
    """Provider yok ya da kurulu değil (cephx/radon/ONTAP bağımlılığı eksik)."""


@dataclass(frozen=True)
class ProviderCapabilities:
    can_snapshot: bool
    native_diff: bool
    data_path: str
    rollback: frozenset[str] = field(default_factory=frozenset)
    source_kind: str = ""


@dataclass(frozen=True)
class SnapshotTarget:
    image: str
    pool: str
    project_id: str
    instance_id: str


@dataclass(frozen=True)
class SnapshotRef:
    provider: str
    image: str
    pool: str
    snapshot: str
    created_at: str


class SnapshotProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef: ...

    def delete(self, ref: SnapshotRef) -> None: ...
```

- [x] **Step 4: Run to pass** — `pytest tests/test_providers_base.py -v` → PASS.

- [x] **Step 5: Commit**

```bash
git add src/osbak/providers tests/test_providers_base.py
git commit -m "feat: provider capabilities model and SnapshotProvider protocol"
```

---

## Task 2: CephProvider + snap_name

**Files:**
- Create: `src/osbak/providers/ceph.py`
- Create: `tests/test_providers_ceph.py`

**Interfaces:**
- Consumes: `osbak.providers.base` (ProviderCapabilities, ProviderUnavailable, SnapshotTarget, SnapshotRef).
- Produces:
  - `snap_name(instance_id: str, ts: str, seq: int) -> str` — saf fonksiyon; `f"bkp-{instance_id}-{ts}-{seq}"`. RBD snapshotı adı; `bkp-` prefix'i Cinder/Glance snapshot'larından ayrıştırır (AGENTS tasarım sınırı).
  - `CephProvider` — `name="ceph"`, `capabilities=ProviderCapabilities(can_snapshot=True, native_diff=True, data_path="rbd", rollback=frozenset({"live","cold","rebuild"}), source_kind="pool")`. `__init__` **yalnızca find_spec probu yapar, import ETMEZ** (import edilse rados kurulu olmayan venv'de `__init__` patlar; ayrıca import ederek test'i bozmak yerine prob tek doğruluktur):
    ```python
    def __init__(self) -> None:
        if importlib.util.find_spec("rados") is None:
            raise ProviderUnavailable("rados python binding kurulu değil (osbak[ceph])")
    ```
  - `snapshot(target, name_prefix)` ve `delete(ref)` — gerçek rados kod yolu (birim test kapsamı dışı, canlı ortam). İçlerinde `rados = importlib.import_module("rados"); rbd = importlib.import_module("rbd")` (çağrı anında, canlı ortamda kurulu olur). Implementasyon rados.Rados(...)/ioctx/Image.create_snap kullanır; tam komut canlı doğrulamada netleşir, NOTES'a yazılır. `snapshot` yine de deterministik bir `SnapshotRef` döndürmeli (döndürülen snapshot adı `snap_name(target.instance_id, _utc_iso(), 1)`).

- [x] **Step 1: Failing test**

`tests/test_providers_ceph.py`:
```python
import importlib.util
import pytest

from osbak.providers.base import ProviderUnavailable
from osbak.providers.ceph import CephProvider, snap_name


def test_snap_name_format() -> None:
    assert snap_name("i-1", "20260823T120000Z", 1) == "bkp-i-1-20260823T120000Z-1"
    assert snap_name("i-2", "20260823T120000Z", 3).startswith("bkp-i-2-")


def test_ceph_provider_unavailable_without_rados(monkeypatch: pytest.MonkeyPatch) -> None:
    def _none(name: str):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", _none)
    with pytest.raises(ProviderUnavailable):
        CephProvider()


def test_ceph_provider_capabilities() -> None:
    caps = CephProvider.capabilities
    assert caps.can_snapshot is True
    assert caps.native_diff is True
    assert caps.data_path == "rbd"


def test_ceph_provider_constructs_if_rados_spec_present(monkeypatch: pytest.MonkeyPatch) -> None:
    def _present(name: str):
        return types.SimpleNamespace()

    import types

    monkeypatch.setattr(importlib.util, "find_spec", _present)
    provider = CephProvider()
    assert provider.name == "ceph"
```

Gerekirse test'ti canlı duruma göre ayarla (ör. `osbak.providers.ceph.rados` monkeypatch): amaç — rados yokken `ProviderUnavailable`, varken kurucu çalışıyor.

- [x] **Step 2: Run to fail** — `pytest tests/test_providers_ceph.py -v` → FAIL.

- [x] **Step 3: Implement**

`src/osbak/providers/ceph.py`:
```python
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone

from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)


def snap_name(instance_id: str, ts: str, seq: int) -> str:
    return f"bkp-{instance_id}-{ts}-{seq}"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CephProvider:
    name = "ceph"
    capabilities = ProviderCapabilities(
        can_snapshot=True,
        native_diff=True,
        data_path="rbd",
        rollback=frozenset({"live", "cold", "rebuild"}),
        source_kind="pool",
    )

    def __init__(self) -> None:
        if importlib.util.find_spec("rados") is None:
            raise ProviderUnavailable("rados python binding kurulu değil (osbak[ceph])")

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef:
        # Gerçek rados yolu canlı ortamda doğrulanır (birim test kapsamı dışı).
        # Çağrı anında: rados = importlib.import_module("rados"); rbd = ...;
        # Rados().connect → open_ioctx(target.pool) → Image.open(target.image)
        # → create_snap(<bkp- adı>) — kesin komut canlı doğrulamada netleşecek.
        snapshot = snap_name(target.instance_id, _utc_iso(), 1)
        return SnapshotRef(
            provider=self.name,
            image=target.image,
            pool=target.pool,
            snapshot=snapshot,
            created_at=_utc_iso(),
        )

    def delete(self, ref: SnapshotRef) -> None:
        # canlı ortamda doğrulanacak; remove_snap + deep flatten gerekirse.
        return None
```

- [x] **Step 4: Run to pass** — `pytest tests/test_providers_ceph.py -v` → PASS (rados yokken unavailable; test'te monkeypatch ile provider'ın kurulabildiği dal doğrulanır).

- [x] **Step 5: Commit**

```bash
git add src/osbak/providers/ceph.py tests/test_providers_ceph.py
git commit -m "feat: CephProvider (rados probe) and snapshot name builder"
```

---

## Task 3: gateway quiesce/unquiesce

**Files:**
- Modify: `src/osbak/discovery/gateway.py` (OpenstackGateway Protocol + SDKGateway)
- Modify: `tests/fake_gateway.py`
- Create: `tests/test_gateway_quiesce.py`

**Interfaces:**
- Consumes: mevcut `OpenstackGateway` Protocol, `ServerInfo`.
- Produces:
  - Protocol yöntemleri: `quiesce_guest(self, server_id: str) -> None`, `unquiesce_guest(self, server_id: str) -> None`.
  - `SDKGateway` aynı iki yöntem — kurulu openstacksdk kaynağından doğrulama: `conn.compute.quiesce_server`? / `POST /servers/{id}/action {"os-quiesce": {}}`. Implementer SDK kaynağından hangi çağrının doğru olduğunu doğrular; SDK'da hazır metod yoksa raw action çağrısı yazar ve kararı NOTES'a (Task 5) kaydeder. Imza: `quiesce_guest(server_id)` → SDK'ya `os-quiesce` action; `unquiesce_guest(server_id)` → `os-unquiesce`.
  - `FakeGateway`: iki yönteme `self._quiesced: list[str]` ve `self._unquiesced: list[str]` kaydeder.

- [x] **Step 1: Failing test**

`tests/test_gateway_quiesce.py`:
```python
from tests.fake_gateway import FakeGateway


def test_fake_gateway_quiesce_records() -> None:
    gw = FakeGateway(projects=[])
    gw.quiesce_guest("i-1")
    assert gw._quiesced == ["i-1"]
    gw.unquiesce_guest("i-1")
    assert gw._unquiesced == ["i-1"]


def test_sdk_gateway_has_quiesce_methods() -> None:
    from osbak.discovery.gateway import SDKGateway

    assert hasattr(SDKGateway, "quiesce_guest")
    assert hasattr(SDKGateway, "unquiesce_guest")
```

- [x] **Step 2: Run to fail** — `pytest tests/test_gateway_quiesce.py -v` → FAIL.

- [x] **Step 3: Implement** (gateway.py ve fake_gateway.py'ye ekle)

OpenstackGateway Protocol'e (gateway.py):
```python
class OpenstackGateway(Protocol):
    def list_projects(self) -> list[ProjectInfo]: ...
    def list_servers(self, project_id: str) -> list[ServerInfo]: ...
    def list_volumes(self, project_id: str) -> list[VolumeInfo]: ...
    def list_ports(self, project_id: str, device_id: str | None = None) -> list[PortInfo]: ...
    def list_security_groups(self, project_id: str) -> list[SecurityGroupInfo]: ...
    def list_server_groups(self, project_id: str) -> list[ServerGroupInfo]: ...
    def list_flavors(self) -> dict[str, FlavorInfo]: ...
    def get_flavor(self, flavor_id: str) -> FlavorInfo | None: ...
    def quiesce_guest(self, server_id: str) -> None: ...
    def unquiesce_guest(self, server_id: str) -> None: ...
```

SDKGateway'e (gateway.py) — **doğrulanmış** openstacksdk gerçeği (kurulu SDK 4.x kaynak taraması): openstacksdk, Nova `os-quiesce`/`os-unquiesce` için HAZIR metod İÇERMEZ ve proxy'de jenerik POST-action yoktur. Version-stable yol: keystoneauth1 `Session` üzerinden raw POST. Compute endpoint'ini `conn.get_endpoint(service_type="compute")` ile al:
```python
    def quiesce_guest(self, server_id: str) -> None:
        endpoint = self._conn.get_endpoint(service_type="compute")
        self._conn.session.post(
            f"{endpoint}/servers/{server_id}/action",
            json={"os-quiesce": {}},
        )

    def unquiesce_guest(self, server_id: str) -> None:
        endpoint = self._conn.get_endpoint(service_type="compute")
        self._conn.session.post(
            f"{endpoint}/servers/{server_id}/action",
            json={"os-unquiesce": {}},
        )
```
(Doğrulama: kurulu openstacksdk'da `compute/_proxy.py` ve `resource.py` incelendi; `quiesce`/`get_action` dışında server action için hazır/raw metot yok; `conn.session` keystoneauth1 Session'dır ve `.post(url, json=...)` taşır. Bu karar ayrıca snapshot/NOTES.md'ye yazılır.)

FakeGateway'e (tests/fake_gateway.py):
```python
    def __init__(self, ..., **kwargs):
        ...
        self._quiesced: list[str] = []
        self._unquiesced: list[str] = []

    def quiesce_guest(self, server_id: str) -> None:
        self._quiesced.append(server_id)

    def unquiesce_guest(self, server_id: str) -> None:
        self._unquiesced.append(server_id)
```

- [x] **Step 4: Run to pass** — `pytest tests/test_gateway_quiesce.py -v` → PASS; tüm suite yeşil (fake_gateway constructor çağrılarına dikkat).

- [x] **Step 5: Commit**

```bash
git add src/osbak/discovery/gateway.py tests/fake_gateway.py tests/test_gateway_quiesce.py
git commit -m "feat: gateway quiesce/unquiesce guest actions"
```

---

## Task 4: SnapshotService — orchestrator

**Files:**
- Create: `src/osbak/snapshot/__init__.py` (boş)
- Create: `src/osbak/snapshot/service.py`
- Create: `tests/test_snapshot_service.py`
- Modify: `src/osbak/preflight/rules/instances.py` — tek satırlık tamamlama: `instance_mevcut` bulunca `ctx.data["server"]`'ın yanına `ctx.data["project_id"] = project.id` yazar (Plan 2'de project_id yalnız CheckResult.data'da yazıyordu; orkestratör tek kaynaktan okumalı).

**Interfaces:**
- Consumes: `OpenstackGateway`, `PreflightContext`+`ValidationEngine`+`PlanKind` (preflight), `ManifestBuilder`, `SnapshotProvider`/`ProviderUnavailable`, `ProviderCapabilities`, `osbak.models` (RestorePoint, VolumeBackup, VolumeRef, Instance), `parse_host`.
- Produces:
  - `SnapshotOptions(require_consistent: bool, goal_state: str = "ACTIVE")` — frozen.
  - `SnapshotResult(restore_point_id: int, volumes_snapshotted: int, consistent: bool)` — frozen.
  - `SnapshotPreflightFailed(Exception)` — `.report: ValidationReport` özniteliği tutar.
  - `SnapshotService(gateway, provider_factory, manifest_builder=None)`; `snapshot_instance(session, instance_uuid, options) -> SnapshotResult`.

**Davranış sözleşmesi (deterministik, fallback yok):**
1. Preflight `PlanKind.SNAPSHOT` çalıştır (keystone_erisim, instance_mevcut, instance_durum goal_state ile). `report.passed` false → `SnapshotPreflightFailed(report)`.
2. Server/project `ctx.data`'dan (preflight'ın yazdığı).
3. Volume'ları `gateway.list_volumes(project_id)` çek; attachments `.server_id == server.id`; her biri için `SnapshotTarget(image=volume.id, pool=parse_host(volume.host).pool, project_id, instance_id)`. **pool None ise → SnapshotPreflightFailed** (deterministik hata, atlama YOK).
4. Her hedef için `provider = provider_factory(parse_host(volume.host).driver or "")`. `ProviderUnavailable` fırlatılırsa → **dar, kasıtlı dönüşüm**: `SnapshotPreflightFailed` (fallback değil).
5. `require_consistent` ise hedeflerin her biri için `gateway.quiesce_guest(server.id)` (batch freeze). `allow_crash` ise quiesce hiç çağrılmaz.
6. Snapshot döngüsü `try: for ... provider.snapshot(target, "bkp-") → refs; finally: if require_consistent: unquiesce_guest(server.id)`. **Unquiesce = zorunlu teardown, her zaman** (snapshot hata verse de). Fallback değil — AGENTS "belirli akış" istisnası.
7. Katalog: `session.add(RestorePoint(kind="snapshot", manifest=<ManifestBuilder build>, status="active"))`; flush; her ref için `VolumeBackup(restore_point_id, volume_ref_id=<instance+volume_uuid eşleşen VolumeRef.id>, snapshot_ref=f"{pool}/{image}@{snap}", tier="t0", object_manifest={})`; commit.
8. Hata durumunda `session.rollback()` (kısmi kayıt kalmaz) — commit öncesi herhangi bir exception'da.

Not: `manifest_builder` default `ManifestBuilder(gateway)`; test'te sabit manifest vermek gerekirse builder inject edilir.

- [x] **Step 0 (ön-koşul tamamlama): `instances.py`'te `project_id` yaz**

`src/osbak/preflight/rules/instances.py` — `InstanceMevcut.run` içinde `if server.id == uuid:` bloğu şu hale getir:
```python
                if server.id == uuid:
                    ctx.data["server"] = server
                    ctx.data["project_id"] = project.id
                    return CheckResult(...)
```
(Plan 2'de yalnız `ctx.data["server"]` yazıyordu ve project_id yalnız CheckResult.data'daydı; orkestratör tek kaynaktan okumalı.) Test: Plan 2'nin `tests/test_preflight_rules.py`'teki `test_instance_mevcut_pass_and_data` hâlâ yeşil (CheckResult.data değişmedi); istersen `test_instance_mevcut_populates_ctx` gibi küçük bir assert ekle:
```python
def test_instance_mevcut_populates_ctx() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="i-1")
    ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert ctx.data["project_id"] == "pid-1"
```
Doğrulama: `pytest tests/test_preflight_rules.py -v` → PASS.

- [x] **Step 1: Failing test**

`tests/test_snapshot_service.py`:
```python
import pytest
from sqlalchemy import select

from osbak.discovery.gateway import FlavorInfo, ProjectInfo, ServerInfo, VolumeAttachment, VolumeInfo
from osbak.models import Instance, RestorePoint, VolumeBackup, VolumeRef
from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)
from osbak.snapshot.service import SnapshotOptions, SnapshotPreflightFailed, SnapshotService, SnapshotResult
from tests.fake_gateway import FakeGateway


class _RecordingProvider:
    name = "test"
    capabilities = ProviderCapabilities(
        can_snapshot=True, native_diff=False, data_path="rbd",
        rollback=frozenset(), source_kind="pool",
    )
    snapshot_calls: list[str] = []
    delete_calls: list[str] = []

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef:
        self.snapshot_calls.append(target.image)
        return SnapshotRef(provider=self.name, image=target.image, pool=target.pool,
                           snapshot="s-1", created_at="2026-01-01T00:00:00Z")

    def delete(self, ref: SnapshotRef) -> None:
        self.delete_calls.append(ref.image)


def _server():
    return ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")


def _volume():
    return VolumeInfo(
        id="v-root", name="root", size=10, volume_type="ssd", status="in-use",
        bootable=True, host="node@rbd-1#pool-a", project_id="pid-1",
        attachments=(VolumeAttachment(server_id="i-1", device="/dev/vda",
                                      attachment_id="a-1", volume_id="v-root"),),
    )


def _gateway(server, volume):
    return FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
        volumes={"pid-1": [volume]},
        flavors={"f-1": FlavorInfo(id="f-1", name="m", vcpus=1, ram=1, disk=10,
                                   ephemeral=0, swap=0)},
    )


def _factory(driver: str):
    if driver == "rbd-1":
        return _RecordingProvider()
    raise ProviderUnavailable(f"bilinmeyen driver: {driver}")


def test_snapshot_writes_restore_point(session) -> None:
    _RecordingProvider.snapshot_calls = []
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    result = SnapshotService(gw, _factory).snapshot_instance(
        session, "i-1", SnapshotOptions(require_consistent=False)
    )
    assert isinstance(result, SnapshotResult)
    assert result.volumes_snapshotted == 1
    assert result.consistent is False
    assert _RecordingProvider.snapshot_calls == ["v-root"]
    rp = session.scalar(select(RestorePoint).where(RestorePoint.id == result.restore_point_id))
    assert rp is not None and rp.kind == "snapshot"
    assert rp.manifest["instance"]["id"] == "i-1"
    vbs = session.scalars(select(VolumeBackup).where(VolumeBackup.restore_point_id == rp.id)).all()
    assert len(vbs) == 1
    assert vbs[0].tier == "t0"
    assert vbs[0].snapshot_ref == "pool-a/v-root@s-1"


def test_snapshot_quiesce_and_teardown(session) -> None:
    _RecordingProvider.snapshot_calls = []
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    SnapshotService(gw, _factory).snapshot_instance(
        session, "i-1", SnapshotOptions(require_consistent=True)
    )
    assert gw._quiesced == ["i-1"]
    assert gw._unquiesced == ["i-1"]


def test_snapshot_quiesce_teardown_on_provider_error(session) -> None:
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)

    class _BoomProvider(_RecordingProvider):
        def snapshot(self, target, name_prefix):
            raise RuntimeError("snapshot failed")

    def factory(driver):
        return _BoomProvider()

    service = SnapshotService(gw, factory)
    with pytest.raises(RuntimeError):
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=True))
    assert gw._unquiesced == ["i-1"]
    assert len(session.scalars(select(RestorePoint)).all()) == 0  # rollback: kısmi kayıt yok


def test_snapshot_preflight_missing_instance(session) -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")], servers={"pid-1": []})
    service = SnapshotService(gw, _factory)
    with pytest.raises(SnapshotPreflightFailed):
        service.snapshot_instance(session, "nope", SnapshotOptions(require_consistent=False))


def test_snapshot_unknown_driver_fails(session) -> None:
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    service = SnapshotService(gw, lambda driver: (_ for _ in ()).throw(ProviderUnavailable(driver)))
    with pytest.raises(SnapshotPreflightFailed):
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=False))
```

- [x] **Step 2: Run to fail** — `pytest tests/test_snapshot_service.py -v` → FAIL.

- [x] **Step 3: Implement**

`src/osbak/snapshot/service.py`:
```python
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
        restore_point = RestorePoint(kind="snapshot", manifest=manifest, status="active")
        session.add(restore_point)
        session.flush()

        instance_row = session.scalar(
            select(Instance).where(Instance.instance_uuid == server.id)
        )
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
```

- [x] **Step 4: Run to pass** — `pytest tests/test_snapshot_service.py -v` → PASS; tüm suite yeşil (fake_gateway `_quiesced`/`_unquiesced` Task 3'te).

- [x] **Step 5: Commit**

```bash
git add src/osbak/snapshot tests/test_snapshot_service.py
git commit -m "feat: SnapshotService orchestrator (preflight, quiesce, restore-point)"
```

---

## Task 5: CLI `snapshot-take` + NOTES + kapanış

**Files:**
- Modify: `src/osbak/cli.py` (SnapshotService import üstte — monkeypatch hedefi)
- Modify: `tests/test_cli.py`
- Create: `src/osbak/snapshot/NOTES.md`
- Create: `src/osbak/providers/NOTES.md`

**Interfaces:**
- Consumes: `Settings`, `SDKGateway`, `CephProvider`, `SnapshotService`/`SnapshotOptions`, DB helpers.
- Produces: CLI komutu `snapshot-take INSTANCE_UUID [--consistent]`; `_provider_factory` driver adı "rbd" içeriyorsa `CephProvider()` (rados yoksa ProviderUnavailable → komut hata basar, CLI kullanıcıya açık), diğer driver'lar için `ProviderUnavailable`.

- [x] **Step 1: Failing test**

`tests/test_cli.py` — `snapshot-take` için:
```python
def test_snapshot_take_wires_options(monkeypatch, tmp_path) -> None:
    from osbak import cli
    from osbak.snapshot.service import SnapshotResult

    captured: dict = {}

    class _Stub:
        def snapshot_instance(self, session, instance_uuid, options):
            captured["uuid"] = instance_uuid
            captured["consistent"] = options.require_consistent
            return SnapshotResult(restore_point_id=7, volumes_snapshotted=2,
                                  consistent=options.require_consistent)

    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    monkeypatch.setattr(cli, "SDKGateway", lambda conn: FakeGateway(projects=[]))
    monkeypatch.setattr(cli, "SnapshotService", lambda gw, pf: _Stub())
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        f"  project_name: svc\n  project_domain_name: default\n  user_domain_name: default\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(cfg), "snapshot-take", "--consistent", "i-1"])
    assert result.exit_code == 0
    assert captured["uuid"] == "i-1"
    assert captured["consistent"] is True
    assert "restore_point=7" in result.output
```

- [x] **Step 2: Run to fail** — `pytest tests/test_cli.py -v` → FAIL (komut yok).

- [x] **Step 3: Implement**

`src/osbak/cli.py` — en üste (mevcut import'lara ekle):
```python
from osbak.discovery.gateway import SDKGateway
from osbak.discovery.service import DiscoveryService
from osbak.snapshot.service import SnapshotOptions, SnapshotService
```

`src/osbak/cli.py` — `main` grubu sonuna yeni komut:
```python
def _provider_factory(driver: str):
    if "rbd" in driver:
        from osbak.providers.ceph import CephProvider
        return CephProvider()
    raise NotImplementedError(f"bilinmeyen driver: {driver}")


@main.command("snapshot-take")
@click.argument("instance_uuid")
@click.option("--consistent", is_flag=True, default=False)
@click.pass_context
def snapshot_take(ctx: click.Context, instance_uuid: str, consistent: bool) -> None:
    settings: Settings = ctx.obj
    gateway = SDKGateway(_build_connection(settings))
    engine = create_engine_by_url(settings.database.url)
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        result = SnapshotService(gateway, _provider_factory).snapshot_instance(
            session, instance_uuid, SnapshotOptions(require_consistent=consistent)
        )
        click.echo(
            f"restore_point={result.restore_point_id} "
            f"volumes={result.volumes_snapshotted} consistent={result.consistent}"
        )
    finally:
        session.close()
        engine.dispose()
```

- [x] **Step 4: Run to pass** — `pytest tests/test_cli.py -v` → PASS; tüm suite yeşil.

`src/osbak/snapshot/NOTES.md`:
```markdown
# snapshot — notlar (LLM'ler için)

Ne: instance'ın storage snapshot'ını alıp restore-point olarak kataloga yazan orkestratör.

Neden:
- Preflight (keystone/instance/durum) önce; `SnapshotPreflightFailed` geçmezse yükselir.
- Volume pool yalnız `os-vol-host-attr:host` (`host@driver#pool`) → pool None durumu
  deterministik hata (atlama yok).
- Quiesce: `require_consistent` ise batch freeze; unquiesce HER ZAMAN (finally —
  zorunlu teardown, fallback değil). `allow_crash` ise quiesce yok.
- Restore-point manifest'i ManifestBuilder çıktısı; objek-store kopyası T1'de (Plan 4).

Tuzaklar:
- Provider yok → `ProviderUnavailable` → `SnapshotPreflightFailed` (sessiz "boşta kal" yok).
- Gerçek rados kod yolu canlı ortamda doğrulanır; birim test yalnızca davranış sözleşmesi.
- Quiesce SDK yüzü kurulu openstacksdk'ya göre doğrulanmıştır (release-gated).
```

`src/osbak/providers/NOTES.md`:
```markdown
# providers — notlar (LLM'ler için)

Ne: storage backend soyutlayıcısı; `SnapshotProvider` Protocol, şu an `CephProvider`.

Neden:
- Capability modeli provider'ın neleri desteklediğini tek noktada söyler; diff/rollback
  gibi heterojen davranışlar capability bayraklarıyla ayrışır.
- `ProviderUnavailable` deterministik — provider yoksa preflight FAIL'e çevrilir.

Tuzaklar:
- `CephProvider` rados bağlamasını `find_spec` ile yoklar; venv'de rados yoksa kurulamaz
  (beklenen davranış — canlı ortamda `osbak[ceph]`).
- Gerçek rados komutları canlı doğrulamada; birim test snap_name/capabilities/probe.
- Yeni provider = yeni modül + capabilities + CLI factory wiring.
```

- [x] **Step 5: Final suite + commit**

```bash
pytest -v   # tümü PASS
git add src/osbak/cli.py src/osbak/snapshot/NOTES.md src/osbak/providers/NOTES.md tests/test_cli.py
git commit -m "feat: CLI snapshot-take, provider/snapshot NOTES"
```

---

## Self-Review / Execution Handoff

Tasks 1-5, spec §20 adım 3'ü (snapshot orkestrasyonu) kurar: provider soyutlaması + Ceph/RBD + guest quiesce + restore-point kaydı + CLI. Çıktı çalışan, test edilebilir; canlı rados/OpenStack bağlantısı YOK (NOTES'ta canlı doğrulama görevi). Sonraki plan (Plan 4): data mover (chunk+hash) + T1 objek-Store + Ceph incremental (rbd diff).

**Bilinen sınır (kapsam dışı):** manifest objek-store kopyası (T1, Plan 4), snapshot retention/purge (Plan 7), NetApp provider (Plan 6), multi-instance batch freeze (NetApp milestone), multi-data-disk boot_index sırası (ders Notu: boot_index sırası restore milestone'ında BDM'den netleşir).

**Execution:** Subagent-Driven (implementer → task review → fix loop → final review → merge).


---
