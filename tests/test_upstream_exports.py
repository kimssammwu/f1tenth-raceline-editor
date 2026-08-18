import json
import math
from pathlib import Path

import numpy as np

from f1tenth_raceline.core import RacelineResult
from f1tenth_raceline.upstream_exports import (
    LTPL_FIELDS,
    WPNT_FIELDS,
    _distances,
    _interp_track_upstream,
    export_upstream_waypoint_json,
    map_info_string,
)


def _result() -> RacelineResult:
    center = np.array([[0., 0., 1., 1.2], [1., 0., 1., 1.2], [1., 1., 1., 1.2]])
    traj = np.array([[0., 0., 0., 0., .1, 2., 0.], [1., 1., 0., .1, .2, 2.5, .1]])
    ltpl = np.arange(24, dtype=float).reshape(2, 12)
    return RacelineResult(center[:, :2], center, np.array([[0., -1.], [1., -1.]]), np.array([[0., 1.], [1., 1.]]), traj, traj.copy(), ltpl, 4.2, 4.5)


def test_upstream_json_names_schema_and_payload(tmp_path: Path) -> None:
    gp, lp = export_upstream_waypoint_json(tmp_path, _result())
    g = json.loads(gp.read_text()); l = json.loads(lp.read_text())
    assert (gp.name, lp.name) == ("global_waypoints.json", "ltpl_waypoints.json")
    assert set(g) == {"map_info_str", "est_lap_time", "centerline_markers", "centerline_waypoints", "global_traj_markers_iqp", "global_traj_wpnts_iqp", "global_traj_markers_sp", "global_traj_wpnts_sp", "trackbounds_markers"}
    assert set(l) == {"map_info_str", "ltpl_traj_wpnts"}
    assert set(g["global_traj_wpnts_iqp"]["wpnts"][0]) == set(WPNT_FIELDS)
    assert set(l["ltpl_traj_wpnts"]["ltplwpnts"][0]) == set(LTPL_FIELDS)
    assert g["est_lap_time"]["data"] == float(np.float32(4.5))
    assert g["centerline_markers"]["markers"]
    assert g["global_traj_markers_iqp"]["markers"]
    assert g["trackbounds_markers"]["markers"]
    assert np.isclose(g["global_traj_wpnts_iqp"]["wpnts"][0]["psi_rad"], np.pi / 2)


def test_ros_message_headers_match_upstream_defaults(tmp_path: Path) -> None:
    gp, lp = export_upstream_waypoint_json(tmp_path, _result())
    g = json.loads(gp.read_text()); l = json.loads(lp.read_text())
    # Upstream never assigns WpntArray/LtplWpntArray headers.
    assert g["centerline_waypoints"]["header"]["frame_id"] == ""
    assert g["global_traj_wpnts_iqp"]["header"]["frame_id"] == ""
    assert g["global_traj_wpnts_sp"]["header"]["frame_id"] == ""
    assert l["ltpl_traj_wpnts"]["header"]["frame_id"] == ""
    # Marker headers are explicitly assigned to the map frame.
    assert g["centerline_markers"]["markers"][0]["header"]["frame_id"] == "map"
    assert g["global_traj_markers_iqp"]["markers"][0]["header"]["frame_id"] == "map"
    assert g["trackbounds_markers"]["markers"][0]["header"]["frame_id"] == "map"


def test_map_info_uses_upstream_round_string_format() -> None:
    result = _result()
    result.est_lap_time_iqp = 1.2
    result.est_lap_time_shortest = 3.4
    result.raceline_iqp[:, 5] = [2.0, 2.5]
    result.raceline_shortest[:, 5] = [3.0, 3.25]
    assert map_info_string(result) == (
        "IQP estimated lap time: 1.2s; IQP maximum speed: 2.5m/s; "
        "SP estimated lap time: 3.4s; SP maximum speed: 3.25m/s; "
    )


def test_estimated_lap_time_is_serialized_as_ros_float32(tmp_path: Path) -> None:
    result = _result()
    result.est_lap_time_shortest = 1.234567890123
    gp, _ = export_upstream_waypoint_json(tmp_path, result)
    g = json.loads(gp.read_text())
    assert g["est_lap_time"]["data"] == float(np.float32(1.234567890123))
    assert g["est_lap_time"]["data"] != result.est_lap_time_shortest


def test_interp_track_matches_pinned_upstream_sampling_contract() -> None:
    reftrack = np.array([
        [0.0, 0.0, 1.0, 2.0],
        [1.0, 0.0, 2.0, 3.0],
        [1.0, 1.0, 3.0, 4.0],
        [0.0, 1.0, 4.0, 5.0],
    ])
    out = _interp_track_upstream(reftrack, stepsize_approx=0.6)
    # Upstream uses ceil(total_length / step) + 1 points including closure,
    # then drops the duplicate final point.
    assert len(out) == math.ceil(4.0 / 0.6)
    assert np.allclose(out[0], reftrack[0])
    assert not np.allclose(out[-1, :2], reftrack[0, :2])


def test_bound_distance_uses_same_closed_linspace_interpolation_as_upstream() -> None:
    bound = np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]])
    xy = np.array([[0.5, 0.5], [0.0, 0.0]])
    dense = _interp_track_upstream(np.column_stack((bound, np.zeros((4, 2)))), 0.1)
    expected = np.array([np.min(np.linalg.norm(dense[:, :2] - point, axis=1)) for point in xy])
    assert np.allclose(_distances(xy, bound), expected)


def test_cli_and_gui_wire_upstream_exports_to_output_dir() -> None:
    root = Path(__file__).parents[1] / "src" / "f1tenth_raceline"
    cli = (root / "cli.py").read_text()
    editor = (root / "editor_server.py").read_text()
    assert "export_upstream_waypoint_json(out, result)" in cli
    assert "export_upstream_waypoint_json(state.raceline_dir, result)" in editor
    assert 'map_yaml.parent / "output"' in cli
    assert 'map_yaml.parent / "output"' in editor
