import json

from click.testing import CliRunner

from osbak.cli import main
from osbak.discovery.gateway import FlavorInfo, ProjectInfo, ServerInfo
from tests.fake_gateway import FakeGateway


def test_help_lists_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "inventory-refresh" in result.output
    assert "manifest-show" in result.output


def test_inventory_refresh_uses_fake_gateway(monkeypatch, tmp_path) -> None:
    from osbak import cli

    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    monkeypatch.setattr(
        cli,
        "SDKGateway",
        lambda conn: FakeGateway(projects=[], servers={}, volumes={}),
    )
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    result = CliRunner().invoke(main, ["--config", str(cfg), "inventory-refresh"])
    assert result.exit_code == 0
    assert "projects=0 instances=0 volumes=0" in result.output


def _fake_gateway() -> FakeGateway:
    return FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="p1")],
        servers={
            "pid-1": [
                ServerInfo(
                    id="i-1",
                    name="web-1",
                    project_id="pid-1",
                    status="ACTIVE",
                    flavor_id="f-1",
                )
            ]
        },
        volumes={},
        ports={},
        security_groups={},
        server_groups={},
        flavors={
            "f-1": FlavorInfo(
                id="f-1",
                name="m1.small",
                vcpus=1,
                ram=1024,
                disk=20,
                ephemeral=0,
                swap=0,
                is_public=True,
            )
        },
    )


def _write_config(tmp_path) -> str:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
    )
    return str(cfg)


def test_manifest_show_success(monkeypatch, tmp_path) -> None:
    from osbak import cli

    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    monkeypatch.setattr(cli, "SDKGateway", lambda conn: _fake_gateway())
    result = CliRunner().invoke(
        main, ["--config", _write_config(tmp_path), "manifest-show", "i-1"]
    )
    assert result.exit_code == 0
    assert '"i-1"' in result.output
    manifest = json.loads(result.output)
    assert manifest["instance"]["id"] == "i-1"


def test_manifest_show_not_found(monkeypatch, tmp_path) -> None:
    from osbak import cli

    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    monkeypatch.setattr(cli, "SDKGateway", lambda conn: _fake_gateway())
    result = CliRunner().invoke(
        main, ["--config", _write_config(tmp_path), "manifest-show", "nope"]
    )
    assert result.exit_code != 0
    assert "instance not found" in result.output


def test_inventory_refresh_unknown_project_raises(monkeypatch, tmp_path) -> None:
    from osbak import cli

    monkeypatch.setattr(cli, "_build_connection", lambda settings: object())
    monkeypatch.setattr(cli, "SDKGateway", lambda conn: FakeGateway(projects=[]))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n  auth_url: https://x\n  username: u\n  password: p\n"
        "  project_name: svc\n"
        f"database:\n  url: sqlite:///{tmp_path}/osbak.db\n"
        "projects:\n  - doesnotexist\n"
    )
    result = CliRunner().invoke(main, ["--config", str(cfg), "inventory-refresh"])
    assert result.exit_code != 0
    assert "not found" in result.output


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
