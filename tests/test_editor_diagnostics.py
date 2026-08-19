from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from f1tenth_raceline.editor_diagnostics import (
    clear_optimizer_diagnostics,
    optimizer_diagnostics_payload,
)


def _write_diag(path: Path, *, curv_idx: int = 2, jump_idx: int = 3, clear_idx: int = 1) -> None:
    rows = []
    for i in range(5):
        rows.append(
            [
                i,
                float(i),
                float(i * 2),
                0.4,
                0.5,
                0.9,
                0.5 if i != clear_idx else 0.1,
                0.2,
                0.05 if i != jump_idx else 0.7,
                0.2 if i != curv_idx else 4.2,
            ]
        )
    np.savetxt(
        path,
        np.asarray(rows),
        delimiter=",",
        fmt="%.6f",
        header=(
            "index,x,y,width_right,width_left,total_width,"
            "total_width_minus_safety,segment_length,width_jump,approx_curvature"
        ),
        comments="",
    )


def _canvas(x: np.ndarray, y: np.ndarray) -> list[list[float]]:
    return [[float(a * 10), float(100 - b * 10)] for a, b in zip(x, y)]


def test_payload_marks_key_hotspots(tmp_path: Path) -> None:
    path = tmp_path / "primary_iqp_width_0.300_failed_solver_call_4.csv"
    _write_diag(path)
    data = optimizer_diagnostics_payload(
        tmp_path,
        _canvas,
        error="constraints are inconsistent",
    )

    assert data["available"] is True
    attempt = data["attempts"][0]
    assert attempt["solver_call"] == 4
    assert attempt["effective_width_m"] == 0.3
    assert attempt["polyline"][4] == [40.0, 20.0]

    markers = {marker["kind"]: marker for marker in attempt["markers"]}
    assert markers["curvature"]["index"] == 2
    assert markers["curvature"]["x"] == 20.0
    assert markers["width_jump"]["index"] == 3
    assert markers["clearance"]["index"] == 1


def test_payload_orders_latest_attempt_first(tmp_path: Path) -> None:
    old = tmp_path / "primary_iqp_failed_solver_call_4.csv"
    new = tmp_path / "primary_iqp_width_0.300_failed_solver_call_4.csv"
    _write_diag(old)
    _write_diag(new)
    os.utime(old, (time.time() - 10, time.time() - 10))
    os.utime(new, None)

    data = optimizer_diagnostics_payload(tmp_path, _canvas)
    assert data["attempts"][0]["id"] == new.name


def test_clear_removes_only_optimizer_diagnostics(tmp_path: Path) -> None:
    failure = tmp_path / "primary_iqp_failed_solver_call_4.csv"
    prepared = tmp_path / "primary_iqp_prepared_reftrack.csv"
    keep = tmp_path / "keep.csv"
    _write_diag(failure)
    prepared.write_text("x", encoding="utf-8")
    keep.write_text("x", encoding="utf-8")

    clear_optimizer_diagnostics(tmp_path)

    assert not failure.exists()
    assert not prepared.exists()
    assert keep.exists()


def test_editor_server_and_client_expose_failure_overlay() -> None:
    root = Path(__file__).parents[1]
    server = (root / "src/f1tenth_raceline/editor_server.py").read_text(encoding="utf-8")
    client = (root / "src/f1tenth_raceline/web/diagnostics.js").read_text(encoding="utf-8")

    assert 'path == "/api/optimizer-diagnostics"' in server
    assert 'path == "/diagnostics.js"' in server
    assert "clear_optimizer_diagnostics(state.raceline_dir / \".work\")" in server
    assert 'src="/diagnostics.js"' in server
    assert "/api/optimizer-diagnostics" in client
    assert "diagnosticOverlay" in client
    assert "실패 위치 숨기기" in client
    assert "focusMarker" in client
