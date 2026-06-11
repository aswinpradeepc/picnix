from pathlib import Path


def test_dockerfile_copies_runtime_packages() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    for package_dir in (
        ".streamlit",
        "config",
        "graph",
        "observability",
        "persistence",
        "tools",
    ):
        assert f"COPY {package_dir} ./{package_dir}" in dockerfile


def test_streamlit_toolbar_uses_viewer_mode() -> None:
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")

    assert 'toolbarMode = "viewer"' in config
