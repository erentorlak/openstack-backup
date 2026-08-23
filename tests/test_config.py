from pathlib import Path
from osbak.config import Settings


def test_settings_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "keystone:\n"
        "  auth_url: https://x:5000/v3\n"
        "  username: u\n"
        "  password: p\n"
        "  project_name: svc\n"
        "database:\n"
        "  url: sqlite:///osbak.db\n"
        "projects: [p1, p2]\n"
    )
    s = Settings.from_yaml(cfg)
    assert s.keystone.auth_url == "https://x:5000/v3"
    assert s.database.url == "sqlite:///osbak.db"
    assert s.projects == ["p1", "p2"]
    assert s.keystone.password.get_secret_value() == "p"
