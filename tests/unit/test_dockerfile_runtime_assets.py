from __future__ import annotations

from pathlib import Path


def test_dockerfile_copies_runtime_assets_for_prod_image():
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "COPY src/ ./src/" in text
    assert "COPY alembic.ini ./alembic.ini" in text
    assert "COPY alembic/ ./alembic/" in text
    assert "COPY data/ ./data/" in text
    assert "COPY scripts/ ./scripts/" in text
