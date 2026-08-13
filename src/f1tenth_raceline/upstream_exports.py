from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .core import RacelineResult

WPNT_FIELDS = ("id", "s_m", "d_m", "x_m", "y_m", "d_right", "d_left", "psi_rad", "kappa_radpm", "vx_mps", "ax_mps2")
LTPL_FIELDS = ("x_ref_m", "y_ref_m", "width_right_m", "width_left_m", "x_normvec_m", "y_normvec_m", "alpha_m", "s_racetraj_m", "psi_racetraj_rad", "kappa_racetraj_radpm", "vx_racetraj_mps", "ax_racetraj_mps2")


def _header() -> dict:
    return {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": "map"}


def _marker(marker_id: int, x: float, y: float, *, marker_type: int, sx: float, sy: float, sz: float, r: float = 0.0, g: float = 0.0, b: float = 0.0, z: float = 0.0) -> dict:
    return {
        "header": _header(), "ns": "", "id": marker_id, "type": marker_type, "action": 0,
        "pose": {"position": {"x": float(x), "y": float(y), "z": float(z)}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}},
        "scale": {"x": sx, "y": sy, "z": sz},
        "color": {"r": r, "g": g, "b": b, "a": 1.0},
        "lifetime": {"sec": 0, "nanosec": 0}, "frame_locked": False, "points": [], "colors": [], "texture_resource": "", "texture": {"header": _header(), "format": "", "data": []}, "uv_coordinates": [], "text": "", "mesh_resource": "", "mesh_file": {"filename": "", "data": []}, "mesh_use_embedded_materials": False,
    }


def _resample_bound(bound: np.ndarray, step: float = 0.1) -> np.ndarray:
    pts = np.asarray(bound, dtype=float)[:, :2]
    if len(pts) < 2:
        return pts
    closed = np.vstack((pts, pts[0]))
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate(([0.0], np.cumsum(seg)))
    if s[-1] <= 0.0:
        return pts
    q = np.arange(0.0, s[-1], step)
    return np.column_stack((np.interp(q, s, closed[:, 0]), np.interp(q, s, closed[:, 1])))


def _distances(xy: np.ndarray, bound: np.ndarray) -> np.ndarray:
    dense = _resample_bound(bound)
    if len(dense) == 0:
        return np.zeros(len(xy))
    return np.array([np.linalg.norm(dense - p, axis=1).min() for p in xy], dtype=float)


def _conv_psi(psi: float) -> float:
    value = float(psi) + np.pi / 2.0
    return value - 2.0 * np.pi if value > np.pi else value


def _wpnt_array(trajectory: np.ndarray, bound_right: np.ndarray, bound_left: np.ndarray) -> dict:
    dr = _distances(trajectory[:, 1:3], bound_right)
    dl = _distances(trajectory[:, 1:3], bound_left)
    wpnts = []
    for i, row in enumerate(trajectory):
        wpnts.append({"id": i, "s_m": float(row[0]), "d_m": 0.0, "x_m": float(row[1]), "y_m": float(row[2]), "d_right": float(dr[i]), "d_left": float(dl[i]), "psi_rad": _conv_psi(row[3]), "kappa_radpm": float(row[4]), "vx_mps": float(row[5]), "ax_mps2": float(row[6])})
    return {"header": _header(), "wpnts": wpnts}


def _trajectory_markers(trajectory: np.ndarray, second: bool = False) -> dict:
    vmax = max(float(np.max(trajectory[:, 5])), 1e-12)
    markers = []
    for i, row in enumerate(trajectory):
        h = float(row[5]) / vmax
        markers.append(_marker(i, row[1], row[2], marker_type=3, sx=0.1, sy=0.1, sz=h, r=1.0, g=1.0 if second else 0.0, z=h / 2.0))
    return {"markers": markers}


def _centerline(result: RacelineResult) -> tuple[dict, dict]:
    rows = result.centerline_with_width
    xy = rows[:, :2]
    n = len(rows)
    psi = np.zeros(n)
    kappa = np.zeros(n)
    if n > 1:
        delta = np.diff(xy, axis=0, append=xy[:1])
        psi = np.arctan2(delta[:, 1], delta[:, 0]) + np.pi / 2.0
        s = np.arange(n, dtype=float) * 0.1
        kappa = np.gradient(np.unwrap(psi), s)
    wpnts = [{"id": i, "s_m": i * 0.1, "d_m": 0.0, "x_m": float(r[0]), "y_m": float(r[1]), "d_right": float(r[2]), "d_left": float(r[3]), "psi_rad": float(psi[i]), "kappa_radpm": float(kappa[i]), "vx_mps": 0.0, "ax_mps2": 0.0} for i, r in enumerate(rows)]
    markers = [_marker(i, r[0], r[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, b=1.0) for i, r in enumerate(rows)]
    return {"header": _header(), "wpnts": wpnts}, {"markers": markers}


def _bounds_markers(result: RacelineResult) -> dict:
    markers = []
    i = 0
    for p in result.bound_right:
        markers.append(_marker(i, p[0], p[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, r=0.5, b=0.5)); i += 1
    for p in result.bound_left:
        markers.append(_marker(i, p[0], p[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, r=0.5, g=1.0)); i += 1
    return {"markers": markers}


def _ltpl_array(ltpl: np.ndarray) -> dict:
    return {"header": _header(), "ltplwpnts": [{field: float(value) for field, value in zip(LTPL_FIELDS, row)} for row in ltpl]}


def map_info_string(result: RacelineResult) -> str:
    return f"IQP estimated lap time: {result.est_lap_time_iqp:.4f}s; IQP maximum speed: {float(np.max(result.raceline_iqp[:, 5])):.4f}m/s; SP estimated lap time: {result.est_lap_time_shortest:.4f}s; SP maximum speed: {float(np.max(result.raceline_shortest[:, 5])):.4f}m/s; "


def export_upstream_waypoint_json(map_dir: Path, result: RacelineResult) -> tuple[Path, Path]:
    map_dir = Path(map_dir)
    map_dir.mkdir(parents=True, exist_ok=True)
    info = map_info_string(result)
    center_wpnts, center_markers = _centerline(result)
    global_payload = {
        "map_info_str": {"data": info}, "est_lap_time": {"data": float(result.est_lap_time_shortest)},
        "centerline_markers": center_markers, "centerline_waypoints": center_wpnts,
        "global_traj_markers_iqp": _trajectory_markers(result.raceline_iqp),
        "global_traj_wpnts_iqp": _wpnt_array(result.raceline_iqp, result.bound_right, result.bound_left),
        "global_traj_markers_sp": _trajectory_markers(result.raceline_shortest, second=True),
        "global_traj_wpnts_sp": _wpnt_array(result.raceline_shortest, result.bound_right, result.bound_left),
        "trackbounds_markers": _bounds_markers(result),
    }
    ltpl_payload = {"map_info_str": {"data": info}, "ltpl_traj_wpnts": _ltpl_array(result.ltpl)}
    gp = map_dir / "global_waypoints.json"; lp = map_dir / "ltpl_waypoints.json"
    gp.write_text(json.dumps(global_payload, indent=2), encoding="utf-8")
    lp.write_text(json.dumps(ltpl_payload, indent=2), encoding="utf-8")
    return gp, lp
