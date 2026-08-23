from click.testing import CliRunner

from osbak.cli import main
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
