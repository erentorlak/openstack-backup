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
