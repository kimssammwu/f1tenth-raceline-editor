from __future__ import annotations

import configparser
import json
from pathlib import Path
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


def _configured_vehicle_width(input_path: str) -> float | None:
    config_file = Path(input_path) / "racecar_f110.ini"
    if not config_file.is_file():
        return None
    parser = configparser.ConfigParser()
    if not parser.read(config_file):
        return None
    try:
        veh_params = json.loads(parser.get("GENERAL_OPTIONS", "veh_params"))
        width = float(veh_params["width"])
    except (configparser.Error, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not np.isfinite(width) or width <= 0.0:
        return None
    return width


def _adaptive_width_candidates(requested: float, vehicle_width: float, step: float = 0.025) -> list[float]:
    """Return decreasing optimization widths, never below the physical vehicle width.

    ``safety_width`` is passed upstream as ``w_veh``. The pinned vehicle config has
    a physical width of 0.30 m while the editor default is 0.40 m, i.e. 5 cm of
    additional margin per side. When the margin itself makes the curvature QP
    infeasible we may progressively consume only that extra margin; we never make
    the optimizer narrower than the configured vehicle.
    """
    requested = float(requested)
    vehicle_width = float(vehicle_width)
    if requested <= vehicle_width + 1e-9:
        return []
    values: list[float] = []
    current = requested - step
    while current > vehicle_width + 1e-9:
        values.append(round(current, 6))
        current -= step
    if not values or abs(values[-1] - vehicle_width) > 1e-9:
        values.append(round(vehicle_width, 6))
    return values


def _validate_final_geometry(result: Any, input_path: str, label: str) -> dict[str, float]:
    """Independently validate XY curvature for every returned optimizer result."""
    from . import optimizer_diagnostics as od

    if not isinstance(result, (tuple, list)) or not result:
        raise RuntimeError(f"{label}: optimizer returned an unexpected result object")
    traj = np.asarray(result[0])
    if traj.ndim != 2 or traj.shape[1] < 5 or len(traj) < 3:
        raise RuntimeError(f"{label}: optimizer trajectory has invalid shape {traj.shape}")
    if not np.all(np.isfinite(traj[:, :5])):
        raise RuntimeError(f"{label}: optimizer trajectory contains non-finite values")

    steps = np.linalg.norm(np.diff(traj[:, 1:3], axis=0), axis=1)
    if len(steps) and float(np.min(steps)) < 1e-6:
        raise RuntimeError(f"{label}: optimizer trajectory contains a degenerate segment")

    curvlim = od._configured_curvature_limit(input_path)
    geometric = geometric_curvature_closed(traj[:, 1:3])
    if not np.all(np.isfinite(geometric)):
        raise RuntimeError(f"{label}: geometric curvature contains non-finite values")
    max_idx = int(np.argmax(np.abs(geometric)))
    max_geom = float(np.max(np.abs(geometric)))
    if curvlim is not None:
        allowed = curvlim + max(0.02, curvlim * 0.02)
        if max_geom > allowed:
            raise RuntimeError(
                f"{label}: returned trajectory is geometrically infeasible: "
                f"max_geometric_curvature={max_geom:.4f}1/m@{max_idx}, "
                f"acceptance_limit={allowed:.4f}1/m"
            )

        raw = np.asarray(traj[:, 4], dtype=float)
        raw_max = float(np.max(np.abs(raw)))
        if raw_max > allowed:
            raw_idx = int(np.argmax(np.abs(raw)))
            traj[:, 4] = geometric
            print(
                f"[WARN] {label}: repaired curvature column after independent XY validation. "
                f"raw_max={raw_max:.4f}1/m@{raw_idx}, geometric_max={max_geom:.4f}1/m@{max_idx}."
            )
    return {"max_geometric_curvature": max_geom, "max_geometric_curvature_index": float(max_idx)}


def install_online_optimizer_recovery() -> None:
    from . import core
    from . import optimizer_diagnostics as od

    if getattr(od, "_online_geometric_recovery_installed", False):
        return

    original_validate = od._validate_fallback_result

    def guarded_validate(result: Any, input_path: str, label: str) -> dict[str, Any]:
        try:
            return original_validate(result=result, input_path=input_path, label=label)
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

    original_run = core.run_optimizer_with_diagnostics

    def adaptive_run_optimizer_with_diagnostics(**kwargs: Any) -> Any:
        label = str(kwargs.get("label", "optimizer"))
        curv_opt_type = str(kwargs.get("curv_opt_type", ""))
        input_path = str(kwargs.get("input_path", ""))
        requested_width = float(kwargs.get("safety_width", 0.0))

        def run_checked(call_kwargs: dict[str, Any], run_label: str) -> Any:
            result = original_run(**call_kwargs)
            _validate_final_geometry(result, input_path, run_label)
            return result

        try:
            return run_checked(dict(kwargs), label)
        except RuntimeError as first_exc:
            if curv_opt_type != "mincurv_iqp":
                raise

            vehicle_width = _configured_vehicle_width(input_path)
            if vehicle_width is None or requested_width <= vehicle_width + 1e-9:
                raise

            candidates = _adaptive_width_candidates(requested_width, vehicle_width)
            failures: list[str] = []
            print(
                f"[WARN] {label}: requested optimization width {requested_width:.3f}m is infeasible. "
                f"Retrying by consuming only the extra safety margin down to the configured "
                f"physical vehicle width {vehicle_width:.3f}m. Curvature limit is unchanged."
            )
            for width in candidates:
                retry_kwargs = dict(kwargs)
                retry_kwargs["safety_width"] = width
                retry_label = f"{label}_width_{width:.3f}"
                retry_kwargs["label"] = retry_label
                try:
                    result = run_checked(retry_kwargs, retry_label)
                    setattr(od, f"_effective_width_{label}", width)
                    print(
                        f"[WARN] {label}: optimization succeeded with effective width={width:.3f}m "
                        f"(requested={requested_width:.3f}m, physical_vehicle_width={vehicle_width:.3f}m)."
                    )
                    return result
                except RuntimeError as retry_exc:
                    failures.append(f"{width:.3f}m: {retry_exc}")

            detail = " | ".join(failures[-3:])
            raise RuntimeError(
                f"{label}: optimization is infeasible even after reducing only the extra safety "
                f"margin from {requested_width:.3f}m down to the physical vehicle width "
                f"{vehicle_width:.3f}m. Curvature limit was not relaxed. Original error: "
                f"{first_exc}. Last adaptive attempts: {detail}"
            ) from first_exc

    core.run_optimizer_with_diagnostics = adaptive_run_optimizer_with_diagnostics
    od._online_geometric_recovery_installed = True
