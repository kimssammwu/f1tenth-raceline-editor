from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trajectory_planning_helpers as tph

from .core import RacelineResult

WPNT_FIELDS = (
    "id",
    "s_m",
    "d_m",
    "x_m",
    "y_m",
    "d_right",
    "d_left",
    "psi_rad",
    "kappa_radpm",
    "vx_mps",
    "ax_mps2",
)
LTPL_FIELDS = (
    "x_ref_m",
    "y_ref_m",
    "width_right_m",
    "width_left_m",
    "x_normvec_m",
    "y_normvec_m",
    "alpha_m",
    "s_racetraj_m",
    "psi_racetraj_rad",
    "kappa_racetraj_radpm",
    "vx_racetraj_mps",
    "ax_racetraj_mps2",
)


def _header(frame_id: str = "") -> dict:
    return {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": frame_id}


def _marker(
    marker_id: int,
    x: float,
    y: float,
    *,
    marker_type: int,
    sx: float,
    sy: float,
    sz: float,
    r: float = 0.0,
    g: float = 0.0,
    b: float = 0.0,
    z: float = 0.0,
) -> dict:
    return {
        "header": _header("map"),
        "ns": "",
        "id": int(marker_id),
        "type": int(marker_type),
        "action": 0,
        "pose": {
            "position": {"x": float(x), "y": float(y), "z": float(z)},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "scale": {"x": float(sx), "y": float(sy), "z": float(sz)},
        "color": {"r": float(r), "g": float(g), "b": float(b), "a": 1.0},
        "lifetime": {"sec": 0, "nanosec": 0},
        "frame_locked": False,
        "points": [],
        "colors": [],
        "texture_resource": "",
        "texture": {"header": _header(), "format": "", "data": []},
        "uv_coordinates": [],
        "text": "",
        "mesh_resource": "",
        "mesh_file": {"filename": "", "data": []},
        "mesh_use_embedded_materials": False,
    }


def _interp_track_upstream(reftrack: np.ndarray, stepsize_approx: float = 0.1) -> np.ndarray:
    """Exact local copy of the pinned upstream interp_track implementation."""
    reftrack = np.asarray(reftrack, dtype=float)
    reftrack_cl = np.vstack((reftrack, reftrack[0]))
    el_lengths = np.sqrt(np.sum(np.power(np.diff(reftrack_cl[:, :2], axis=0), 2), axis=1))
    dists_cum = np.cumsum(el_lengths)
    dists_cum = np.insert(dists_cum, 0, 0.0)
    no_points_interp = math.ceil(float(dists_cum[-1]) / stepsize_approx) + 1
    dists_interp = np.linspace(0.0, float(dists_cum[-1]), no_points_interp)
    reftrack_interp_cl = np.zeros((no_points_interp, 4), dtype=float)
    reftrack_interp_cl[:, 0] = np.interp(dists_interp, dists_cum, reftrack_cl[:, 0])
    reftrack_interp_cl[:, 1] = np.interp(dists_interp, dists_cum, reftrack_cl[:, 1])
    reftrack_interp_cl[:, 2] = np.interp(dists_interp, dists_cum, reftrack_cl[:, 2])
    reftrack_interp_cl[:, 3] = np.interp(dists_interp, dists_cum, reftrack_cl[:, 3])
    return reftrack_interp_cl[:-1]


def _distances(xy: np.ndarray, bound: np.ndarray) -> np.ndarray:
    points = np.asarray(xy, dtype=float)
    pts = np.asarray(bound, dtype=float)[:, :2]
    if len(pts) == 0:
        return np.zeros(len(points), dtype=float)
    if len(pts) == 1:
        # Real planner bounds are closed contours with many points. Supporting a
        # single-point bound keeps exporter/unit-test fixtures robust without
        # changing the upstream algorithm for valid planner output.
        return np.linalg.norm(points - pts[0], axis=1)
    tmp = np.column_stack((pts, np.zeros((pts.shape[0], 2), dtype=float)))
    dense = _interp_track_upstream(tmp, stepsize_approx=0.1)
    return np.array(
        [
            np.amin(
                np.sqrt(
                    np.power(dense[:, 0] - point[0], 2)
                    + np.power(dense[:, 1] - point[1], 2)
                )
            )
            for point in points
        ],
        dtype=float,
    )


def _infer_reverse(result: RacelineResult) -> bool:
    rows = np.asarray(result.centerline_with_width, dtype=float)
    if len(rows) == 0 or rows.shape[1] < 4:
        return False
    try:
        raw_right = _distances(rows[:, :2], result.bound_right)
        raw_left = _distances(rows[:, :2], result.bound_left)
    except (ValueError, IndexError):
        return False
    normal_error = float(np.mean(np.abs(rows[:, 2] - raw_right) + np.abs(rows[:, 3] - raw_left)))
    reverse_error = float(np.mean(np.abs(rows[:, 2] - raw_left) + np.abs(rows[:, 3] - raw_right)))
    return reverse_error + 1e-9 < normal_error


def _conv_psi(psi: float) -> float:
    new_psi = float(psi) + np.pi / 2.0
    if new_psi > np.pi:
        new_psi = new_psi - 2.0 * np.pi
    return float(new_psi)


def _wpnt_array(
    trajectory: np.ndarray,
    bound_right: np.ndarray,
    bound_left: np.ndarray,
    *,
    reverse: bool = False,
) -> dict:
    trajectory = np.asarray(trajectory, dtype=float)
    d_right = _distances(trajectory[:, 1:3], bound_right)
    d_left = _distances(trajectory[:, 1:3], bound_left)
    if reverse:
        d_right, d_left = d_left, d_right
    wpnts = []
    for i, pnt in enumerate(trajectory):
        wpnts.append(
            {
                "id": int(i),
                "s_m": float(pnt[0]),
                "d_m": 0.0,
                "x_m": float(pnt[1]),
                "y_m": float(pnt[2]),
                "d_right": float(d_right[i]),
                "d_left": float(d_left[i]),
                "psi_rad": _conv_psi(pnt[3]),
                "kappa_radpm": float(pnt[4]),
                "vx_mps": float(pnt[5]),
                "ax_mps2": float(pnt[6]),
            }
        )
    return {"header": _header(), "wpnts": wpnts}


def _trajectory_markers(trajectory: np.ndarray, second_traj: bool = False) -> dict:
    trajectory = np.asarray(trajectory, dtype=float)
    max_vx_mps = float(np.max(trajectory[:, 5]))
    markers = []
    for i, pnt in enumerate(trajectory):
        height = float(pnt[5]) / max_vx_mps
        markers.append(
            _marker(
                i,
                pnt[1],
                pnt[2],
                marker_type=3,
                sx=0.1,
                sy=0.1,
                sz=height,
                r=1.0,
                g=1.0 if second_traj else 0.0,
                z=height / 2.0,
            )
        )
    return {"markers": markers}


def _centerline(result: RacelineResult) -> tuple[dict, dict]:
    rows = np.asarray(result.centerline_with_width, dtype=float)
    centerline_coords = rows[:, :2]
    n_points = len(rows)
    if n_points < 2:
        psi_centerline = np.zeros(n_points, dtype=float)
        kappa_centerline = np.zeros(n_points, dtype=float)
    else:
        psi_centerline, kappa_centerline = tph.calc_head_curv_num.calc_head_curv_num(
            path=centerline_coords,
            el_lengths=0.1 * np.ones(n_points - 1),
            is_closed=False,
        )
    wpnts = []
    markers = []
    for i, row in enumerate(rows):
        wpnts.append(
            {
                "id": int(i),
                "s_m": float(i * 0.1),
                "d_m": 0.0,
                "x_m": float(row[0]),
                "y_m": float(row[1]),
                "d_right": float(row[2]),
                "d_left": float(row[3]),
                "psi_rad": float(psi_centerline[i] + np.pi / 2.0),
                "kappa_radpm": float(kappa_centerline[i]),
                "vx_mps": 0.0,
                "ax_mps2": 0.0,
            }
        )
        markers.append(_marker(i, row[0], row[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, b=1.0))
    return {"header": _header(), "wpnts": wpnts}, {"markers": markers}


def _bounds_markers(result: RacelineResult) -> dict:
    markers = []
    marker_id = 0
    for pnt in np.asarray(result.bound_right, dtype=float):
        markers.append(_marker(marker_id, pnt[0], pnt[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, r=0.5, b=0.5))
        marker_id += 1
    for pnt in np.asarray(result.bound_left, dtype=float):
        markers.append(_marker(marker_id, pnt[0], pnt[1], marker_type=2, sx=0.05, sy=0.05, sz=0.05, r=0.5, g=1.0))
        marker_id += 1
    return {"markers": markers}


def _ltpl_array(ltpl: np.ndarray) -> dict:
    return {
        "header": _header(),
        "ltplwpnts": [
            {field: float(value) for field, value in zip(LTPL_FIELDS, row)}
            for row in np.asarray(ltpl, dtype=float)
        ],
    }


def map_info_string(result: RacelineResult) -> str:
    return (
        f"IQP estimated lap time: {round(float(result.est_lap_time_iqp), 4)}s; "
        f"IQP maximum speed: {round(float(np.amax(result.raceline_iqp[:, 5])), 4)}m/s; "
        f"SP estimated lap time: {round(float(result.est_lap_time_shortest), 4)}s; "
        f"SP maximum speed: {round(float(np.amax(result.raceline_shortest[:, 5])), 4)}m/s; "
    )


def export_upstream_waypoint_json(map_dir: Path, result: RacelineResult) -> tuple[Path, Path]:
    map_dir = Path(map_dir)
    map_dir.mkdir(parents=True, exist_ok=True)
    map_info_str = map_info_string(result)
    centerline_waypoints, centerline_markers = _centerline(result)
    reverse_value = getattr(result, "reverse", None)
    reverse = _infer_reverse(result) if reverse_value is None else bool(reverse_value)
    sp_bound_right = getattr(result, "bound_right_sp", None)
    sp_bound_left = getattr(result, "bound_left_sp", None)
    if sp_bound_right is None:
        sp_bound_right = result.bound_right
    if sp_bound_left is None:
        sp_bound_left = result.bound_left

    global_payload = {
        "map_info_str": {"data": map_info_str},
        "est_lap_time": {"data": float(np.float32(result.est_lap_time_shortest))},
        "centerline_markers": centerline_markers,
        "centerline_waypoints": centerline_waypoints,
        "global_traj_markers_iqp": _trajectory_markers(result.raceline_iqp),
        "global_traj_wpnts_iqp": _wpnt_array(
            result.raceline_iqp, result.bound_right, result.bound_left, reverse=reverse
        ),
        "global_traj_markers_sp": _trajectory_markers(result.raceline_shortest, second_traj=True),
        "global_traj_wpnts_sp": _wpnt_array(
            result.raceline_shortest, sp_bound_right, sp_bound_left, reverse=reverse
        ),
        "trackbounds_markers": _bounds_markers(result),
    }
    ltpl_payload = {
        "map_info_str": {"data": map_info_str},
        "ltpl_traj_wpnts": _ltpl_array(result.ltpl),
    }
    global_path = map_dir / "global_waypoints.json"
    ltpl_path = map_dir / "ltpl_waypoints.json"
    global_path.write_text(json.dumps(global_payload, indent=2), encoding="utf-8")
    ltpl_path.write_text(json.dumps(ltpl_payload, indent=2), encoding="utf-8")
    return global_path, ltpl_path
