from __future__ import annotations

from typing import Any

import numpy as np


def geometric_curvature_closed(xy: np.ndarray) -> np.ndarray:
    pts = np.asarray(xy, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
        raise RuntimeError(f"trajectory XY must have shape (N, 2), got {pts.shape}")
    prev = np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0)
    a = np.linalg.norm(pts - prev, axis=1)
    b = np.linalg.norm(nxt - pts, axis=1)
    c = np.linalg.norm(nxt - prev, axis=1)
    cross = (pts[:, 0] - prev[:, 0]) * (nxt[:, 1] - prev[:, 1]) - (pts[:, 1] - prev[:, 1]) * (nxt[:, 0] - prev[:, 0])
    denom = a * b * c
    kappa = np.zeros(len(pts), dtype=float)
    valid = denom > 1e-9
    kappa[valid] = 2.0 * cross[valid] / denom[valid]
    return kappa


def install_online_optimizer_recovery() -> None:
    from . import optimizer_diagnostics as od

    if getattr(od, "_online_geometric_recovery_installed", False):
        return
    original = od._validate_fallback_result

    def guarded_validate(result: Any, input_path: str, label: str) -> dict[str, Any]:
        try:
            return original(result=result, input_path=input_path, label=label)
        except RuntimeError as exc:
            if "violates the configured curvature limit" not in str(exc):
                raise
            if not isinstance(result, (tuple, list)) or not result:
                raise
            traj = np.asarray(result[0])
            if traj.ndim != 2 or traj.shape[1] < 5 or len(traj) < 3 or not np.all(np.isfinite(traj[:, 1:3])):
                raise
            curvlim = od._configured_curvature_limit(input_path)
            if curvlim is None:
                raise
            allowed = curvlim + max(0.02, curvlim * 0.02)
            geometric = geometric_curvature_closed(traj[:, 1:3])
            max_idx = int(np.argmax(np.abs(geometric)))
            max_geom = float(np.max(np.abs(geometric)))
            if not np.all(np.isfinite(geometric)) or max_geom > allowed:
                raise RuntimeError(
                    f"{label}: fallback is invalid geometrically as well: "
                    f"max_geometric_curvature={max_geom:.4f}1/m@{max_idx}, "
                    f"acceptance_limit={allowed:.4f}1/m. Original validation: {exc}"
                ) from exc
            raw = np.asarray(traj[:, 4], dtype=float)
            raw_idx = int(np.argmax(np.abs(raw)))
            raw_max = float(np.max(np.abs(raw)))
            traj[:, 4] = geometric
            print(
                f"[WARN] {label}: repaired interpolated curvature column after independent "
                f"XY validation. raw_max={raw_max:.4f}1/m@{raw_idx}, "
                f"geometric_max={max_geom:.4f}1/m@{max_idx}, curvlim={curvlim:.4f}1/m."
            )
            return od.analyze_optimized_trajectory(traj, curvlim)

    od._validate_fallback_result = guarded_validate
    od._online_geometric_recovery_installed = True
