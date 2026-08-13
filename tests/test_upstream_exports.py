import json
from pathlib import Path

import numpy as np

from f1tenth_raceline.core import RacelineResult
from f1tenth_raceline.upstream_exports import LTPL_FIELDS, WPNT_FIELDS, export_upstream_waypoint_json


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
    assert g["est_lap_time"]["data"] == 4.5
    assert g["centerline_markers"]["markers"]
    assert g["global_traj_markers_iqp"]["markers"]
    assert g["trackbounds_markers"]["markers"]
    assert np.isclose(g["global_traj_wpnts_iqp"]["wpnts"][0]["psi_rad"], np.pi / 2)


def test_cli_and_gui_wire_upstream_exports_to_output_dir() -> None:
    root = Path(__file__).parents[1] / "src" / "f1tenth_raceline"
    cli = (root / "cli.py").read_text()
    editor = (root / "editor_server.py").read_text()
    assert "export_upstream_waypoint_json(out, result)" in cli
    assert "export_upstream_waypoint_json(state.raceline_dir, result)" in editor
    assert 'map_yaml.parent / "output"' in cli
    assert 'map_yaml.parent / "output"' in editor
