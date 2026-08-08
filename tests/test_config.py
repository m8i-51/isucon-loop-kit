from pathlib import Path

from isuctl.config import Host, IsuconConfig, ProjectConfig, SshConfig, load_config, save_config


def test_roundtrip(tmp_path: Path):
    cfg = IsuconConfig(
        project=ProjectConfig(name="demo", local_dir=str(tmp_path / "work")),
        ssh=SshConfig(user="isucon", key="~/.ssh/id_ed25519"),
        hosts=[Host(name="app1", host="1.2.3.4", role=["app", "web"])],
    )
    path = tmp_path / "isucon.toml"
    save_config(path, cfg)
    loaded = load_config(path)
    assert loaded.project.name == "demo"
    assert loaded.hosts[0].host == "1.2.3.4"
    assert "app" in loaded.hosts[0].role
