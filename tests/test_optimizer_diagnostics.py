from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from f1tenth_raceline.optimizer_diagnostics import (
    analyze_reftrack,
    run_optimizer_with_diagnostics,
)


def _tph_with_solver(solver):
    return SimpleNamespace(
        opt_min_curv=SimpleNamespace(opt_min_curv=solver),
    )


def test_analyze_reftrack_flags_invalid_geometry():
    track = np.array(
        [
            [0.0, 0.0, 0.30, 0.30],
            [1.0, 0.0, 0.10, 0.10],
            [1.0, 0.0, -0.05, 0.50],
        ]
    )

    diag = analyze_reftrack(track, safety_width=0.40)

    assert diag["too_narrow_indices"] == [1]
    assert diag["negative_width_indices"] == [2]
    assert 1 in diag["duplicate_indices"]
    assert diag["min_clearance_margin"] == pytest.approx(-0.20)


def test_iqp_failure_dumps_iteration_and_falls_back_same_width(tmp_path: Path):
    calls = []

    def opt_min_curv(*args, **kwargs):
        reftrack = kwargs["reftrack"]
        calls.append((kwargs["w_veh"], reftrack.copy()))
        if len(calls) == 1:
            raise ValueError("constraints are inconsistent, no solution")
        return np.zeros(len(reftrack)), 0.0

    tph = _tph_with_solver(opt_min_curv)
    original_solver = tph.opt_min_curv.opt_min_curv
    track = np.array(
        [
            [0.0, 0.0, 0.6, 0.6],
            [1.0, 0.0, 0.6, 0.6],
            [1.0, 1.0, 0.6, 0.6],
        ]
    )
    optimizer_calls = []

    def trajectory_optimizer(**kwargs):
        optimizer_calls.append((kwargs["curv_opt_type"], kwargs["safety_width"]))
        tph.opt_min_curv.opt_min_curv(
            reftrack=track,
            w_veh=kwargs["safety_width"],
        )
        return ("traj", "br", "bl", 1.2, "ltpl")

    result = run_optimizer_with_diagnostics(
        tph=tph,
        trajectory_optimizer=trajectory_optimizer,
        input_path="config",
        track_name="track",
        curv_opt_type="mincurv_iqp",
        safety_width=0.4,
        plot=False,
        diagnostics_dir=tmp_path,
        label="primary_iqp",
    )

    assert result[0] == "traj"
    assert optimizer_calls == [("mincurv_iqp", 0.4), ("mincurv", 0.4)]
    assert tph.opt_min_curv.opt_min_curv is original_solver
    assert (tmp_path / "primary_iqp_prepared_reftrack.csv").is_file()
    assert (tmp_path / "primary_iqp_failed_solver_call_1.csv").is_file()
    assert (tmp_path / "primary_iqp_fallback_mincurv_prepared_reftrack.csv").is_file()


def test_non_iqp_failure_does_not_change_algorithm(tmp_path: Path):
    def opt_min_curv(*args, **kwargs):
        raise ValueError("boom")

    tph = _tph_with_solver(opt_min_curv)
    track = np.array(
        [
            [0.0, 0.0, 0.6, 0.6],
            [1.0, 0.0, 0.6, 0.6],
            [1.0, 1.0, 0.6, 0.6],
        ]
    )
    optimizer_calls = []

    def trajectory_optimizer(**kwargs):
        optimizer_calls.append(kwargs["curv_opt_type"])
        tph.opt_min_curv.opt_min_curv(
            reftrack=track,
            w_veh=kwargs["safety_width"],
        )

    with pytest.raises(RuntimeError, match="minimum-curvature QP failed"):
        run_optimizer_with_diagnostics(
            tph=tph,
            trajectory_optimizer=trajectory_optimizer,
            input_path="config",
            track_name="track",
            curv_opt_type="mincurv",
            safety_width=0.4,
            plot=False,
            diagnostics_dir=tmp_path,
            label="plain_mincurv",
        )

    assert optimizer_calls == ["mincurv"]
