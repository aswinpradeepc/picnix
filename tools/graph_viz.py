"""
Utility to export the compiled LangGraph as a Mermaid diagram and optionally a PNG.
Called automatically in development mode (DEBUG=true in .env).
Output: docs/graph.mmd and docs/graph.png (if pygraphviz is available).
"""
from __future__ import annotations

from pathlib import Path

from config.settings import SETTINGS


def export_graph_diagram() -> None:
    """Export the compiled graph to docs/graph.mmd and docs/graph.png when DEBUG is enabled."""
    if not SETTINGS.debug:
        return

    from graph.graph import build_graph  # local import avoids circular deps at module load

    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)

    compiled = build_graph()
    mermaid_text = compiled.get_graph().draw_mermaid()
    (docs_dir / "graph.mmd").write_text(mermaid_text, encoding="utf-8")

    try:
        png_bytes = compiled.get_graph().draw_mermaid_png()
        (docs_dir / "graph.png").write_bytes(png_bytes)
    except Exception:
        pass
