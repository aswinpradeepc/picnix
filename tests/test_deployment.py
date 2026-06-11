from pathlib import Path


def test_dockerfile_copies_runtime_packages() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    for package_dir in (
        ".streamlit",
        "config",
        "graph",
        "observability",
        "pages",
        "persistence",
        "tools",
    ):
        assert f"COPY {package_dir} ./{package_dir}" in dockerfile


def test_dockerfile_installs_node_for_phoenix_mcp() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "nodejs" in dockerfile
    assert "@arizeai/phoenix-mcp" in dockerfile


def test_compose_app_gets_phoenix_base_url() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "PHOENIX_BASE_URL: http://phoenix:6006" in compose


def test_streamlit_toolbar_uses_viewer_mode() -> None:
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")

    assert 'toolbarMode = "viewer"' in config
