from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import numpy as np

_FAILURE_GLOB = "*_failed_solver_call_*.csv"
_SOLVER_CALL_RE = re.compile(r"_failed_solver_call_(\d+)\.csv$")
_WIDTH_RE = re.compile(r"_width_(\d+\.\d+)")


def clear_optimizer_diagnostics(work_dir: Path) -> None:
    work = Path(work_dir)
    if not work.is_dir():
        return
    for pattern in (_FAILURE_GLOB, "*_prepared_reftrack.csv"):
        for path in work.glob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _attempt_label(path: Path) -> str:
    stem = path.name
    width_match = _WIDTH_RE.search(stem)
    call_match = _SOLVER_CALL_RE.search(stem)
    width = f"폭 {float(width_match.group(1)):.3f} m" if width_match else "기본 폭"
    call = f"solver call {call_match.group(1)}" if call_match else "solver 실패"
    if "fallback_mincurv" in stem:
        mode = "mincurv fallback"
    elif "secondary_iqp" in stem:
        mode = "secondary IQP"
    else:
        mode = "primary IQP"
    return f"{mode} · {width} · {call}"


def _marker(
    kind: str,
    row: np.void,
    canvas_xy: tuple[float, float],
    value: float,
    label: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "index": int(row["index"]),
        "x": float(canvas_xy[0]),
        "y": float(canvas_xy[1]),
        "value": float(value),
        "label": label,
        "detail": detail,
    }


def _load_attempt(
    path: Path,
    to_canvas: Callable[[np.ndarray, np.ndarray], list[list[float]]],
) -> dict[str, Any] | None:
    try:
        rows = np.atleast_1d(np.genfromtxt(path, delimiter=",", names=True))
    except (OSError, ValueError):
        return None
    names = set(rows.dtype.names or ())
    required = {
        "index",
        "x",
        "y",
        "width_right",
        "width_left",
        "total_width",
        "total_width_minus_safety",
        "segment_length",
        "width_jump",
        "approx_curvature",
    }
    if not required.issubset(names) or rows.size == 0:
        return None

    x = np.asarray(rows["x"], dtype=float)
    y = np.asarray(rows["y"], dtype=float)
    finite_xy = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite_xy):
        return None

    canvas = to_canvas(x, y)
    if len(canvas) != len(rows):
        return None
    polyline = [[float(p[0]), float(p[1])] for p in canvas]

    curvature = np.asarray(rows["approx_curvature"], dtype=float)
    width_jump = np.asarray(rows["width_jump"], dtype=float)
    clearance = np.asarray(rows["total_width_minus_safety"], dtype=float)

    def finite_argmax(values: np.ndarray) -> int | None:
        mask = np.isfinite(values)
        if not np.any(mask):
            return None
        return int(np.argmax(np.where(mask, values, -np.inf)))

    def finite_argmin(values: np.ndarray) -> int | None:
        mask = np.isfinite(values)
        if not np.any(mask):
            return None
        return int(np.argmin(np.where(mask, values, np.inf)))

    markers: list[dict[str, Any]] = []
    i_curv = finite_argmax(curvature)
    if i_curv is not None:
        row = rows[i_curv]
        value = float(curvature[i_curv])
        markers.append(
            _marker(
                "curvature",
                row,
                tuple(canvas[i_curv]),
                value,
                "최대 근사 곡률",
                f"곡률 {value:.3f} 1/m · 좌 {float(row['width_left']):.3f} m · 우 {float(row['width_right']):.3f} m",
            )
        )

    i_jump = finite_argmax(width_jump)
    if i_jump is not None and i_jump != i_curv:
        row = rows[i_jump]
        value = float(width_jump[i_jump])
        markers.append(
            _marker(
                "width_jump",
                row,
                tuple(canvas[i_jump]),
                value,
                "최대 폭 급변",
                f"폭 변화 {value:.3f} m · 총 폭 {float(row['total_width']):.3f} m",
            )
        )

    i_clear = finite_argmin(clearance)
    if i_clear is not None and i_clear not in {i_curv, i_jump}:
        row = rows[i_clear]
        value = float(clearance[i_clear])
        markers.append(
            _marker(
                "clearance",
                row,
                tuple(canvas[i_clear]),
                value,
                "최소 안전 여유",
                f"안전 여유 {value:.3f} m · 총 폭 {float(row['total_width']):.3f} m",
            )
        )

    call_match = _SOLVER_CALL_RE.search(path.name)
    width_match = _WIDTH_RE.search(path.name)
    return {
        "id": path.name,
        "label": _attempt_label(path),
        "file": path.name,
        "solver_call": int(call_match.group(1)) if call_match else None,
        "effective_width_m": float(width_match.group(1)) if width_match else None,
        "mtime": float(path.stat().st_mtime),
        "polyline": polyline,
        "markers": markers,
        "point_count": int(len(rows)),
    }


def optimizer_diagnostics_payload(
    work_dir: Path,
    to_canvas: Callable[[np.ndarray, np.ndarray], list[list[float]]],
    *,
    error: str | None = None,
    max_attempts: int = 8,
) -> dict[str, Any]:
    work = Path(work_dir)
    if not work.is_dir():
        return {
            "available": False,
            "message": "현재 생성 작업의 최적화 진단 파일이 없습니다.",
            "attempts": [],
            "error": error,
        }

    paths = sorted(
        work.glob(_FAILURE_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    attempts = []
    for path in paths[:max_attempts]:
        attempt = _load_attempt(path, to_canvas)
        if attempt is not None:
            attempts.append(attempt)

    if not attempts:
        return {
            "available": False,
            "message": "시각화할 solver 실패 진단 데이터가 없습니다.",
            "attempts": [],
            "error": error,
        }

    return {
        "available": True,
        "message": (
            "표시 지점은 실패한 reftrack에서 가장 강한 이상값입니다. "
            "QP infeasible의 단일 원인 지점이라고 단정하지 않습니다."
        ),
        "attempts": attempts,
        "selected_attempt_id": attempts[0]["id"],
        "error": error,
    }
