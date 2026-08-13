from __future__ import annotations

import configparser
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np


def analyze_reftrack(reftrack: np.ndarray, safety_width: float) -> dict[str, Any]:
    """Return compact geometry/constraint diagnostics for a TPH reftrack."""
    track = np.asarray(reftrack, dtype=float)
    if track.ndim != 2 or track.shape[1] < 4:
        raise ValueError(f"reftrack must have shape (N, >=4), got {track.shape}")
    if len(track) < 3:
        raise ValueError("reftrack must contain at least 3 points")

    xy = track[:, :2]
    wr = track[:, 2]
    wl = track[:, 3]
    total = wr + wl

    delta = np.roll(xy, -1, axis=0) - xy
    seg_len = np.linalg.norm(delta, axis=1)
    headings = np.arctan2(delta[:, 1], delta[:, 0])
    heading_delta = np.arctan2(
        np.sin(np.roll(headings, -1) - headings),
        np.cos(np.roll(headings, -1) - headings),
    )
    local_ds = np.maximum((seg_len + np.roll(seg_len, -1)) * 0.5, 1e-12)
    approx_curvature = np.abs(heading_delta) / local_ds

    width_jump = np.maximum(
        np.abs(np.roll(wr, -1) - wr),
        np.abs(np.roll(wl, -1) - wl),
    )

    finite_rows = np.all(np.isfinite(track[:, :4]), axis=1)
    too_narrow = total < float(safety_width)
    negative_width = (wr < 0.0) | (wl < 0.0)
    duplicate_like = seg_len < 1e-6

    def _argmin(values: np.ndarray) -> int:
        finite = np.where(np.isfinite(values), values, np.inf)
        return int(np.argmin(finite))

    def _argmax(values: np.ndarray) -> int:
        finite = np.where(np.isfinite(values), values, -np.inf)
        return int(np.argmax(finite))

    return {
        "points": int(len(track)),
        "safety_width": float(safety_width),
        "nonfinite_indices": np.flatnonzero(~finite_rows).astype(int).tolist(),
        "negative_width_indices": np.flatnonzero(negative_width).astype(int).tolist(),
        "too_narrow_indices": np.flatnonzero(too_narrow).astype(int).tolist(),
        "duplicate_indices": np.flatnonzero(duplicate_like).astype(int).tolist(),
        "min_right_width": float(np.nanmin(wr)),
        "min_right_width_index": _argmin(wr),
        "min_left_width": float(np.nanmin(wl)),
        "min_left_width_index": _argmin(wl),
        "min_total_width": float(np.nanmin(total)),
        "min_total_width_index": _argmin(total),
        "min_clearance_margin": float(np.nanmin(total - float(safety_width))),
        "min_segment_length": float(np.nanmin(seg_len)),
        "min_segment_length_index": _argmin(seg_len),
        "max_segment_length": float(np.nanmax(seg_len)),
        "max_segment_length_index": _argmax(seg_len),
        "max_width_jump": float(np.nanmax(width_jump)),
        "max_width_jump_index": _argmax(width_jump),
        "max_approx_curvature": float(np.nanmax(approx_curvature)),
        "max_approx_curvature_index": _argmax(approx_curvature),
    }


def format_reftrack_diagnostics(diag: dict[str, Any]) -> str:
    parts = [
        f"points={diag['points']}",
        f"safety_width={diag['safety_width']:.3f}m",
        (
            f"min_total_width={diag['min_total_width']:.3f}m"
            f"@{diag['min_total_width_index']}"
        ),
        f"min_clearance_margin={diag['min_clearance_margin']:.3f}m",
        (
            f"min_right={diag['min_right_width']:.3f}m"
            f"@{diag['min_right_width_index']}"
        ),
        (
            f"min_left={diag['min_left_width']:.3f}m"
            f"@{diag['min_left_width_index']}"
        ),
        (
            f"min_step={diag['min_segment_length']:.6f}m"
            f"@{diag['min_segment_length_index']}"
        ),
        (
            f"max_step={diag['max_segment_length']:.3f}m"
            f"@{diag['max_segment_length_index']}"
        ),
        (
            f"max_width_jump={diag['max_width_jump']:.3f}m"
            f"@{diag['max_width_jump_index']}"
        ),
        (
            f"max_approx_curvature={diag['max_approx_curvature']:.3f}1/m"
            f"@{diag['max_approx_curvature_index']}"
        ),
    ]
    if diag["too_narrow_indices"]:
        parts.append(f"too_narrow={diag['too_narrow_indices'][:12]}")
    if diag["negative_width_indices"]:
        parts.append(f"negative_width={diag['negative_width_indices'][:12]}")
    if diag["duplicate_indices"]:
        parts.append(f"duplicate_like={diag['duplicate_indices'][:12]}")
    if diag["nonfinite_indices"]:
        parts.append(f"nonfinite={diag['nonfinite_indices'][:12]}")
    return ", ".join(parts)


def write_reftrack_diagnostics(
    path: Path,
    reftrack: np.ndarray,
    safety_width: float,
) -> None:
    track = np.asarray(reftrack, dtype=float)
    xy = track[:, :2]
    wr = track[:, 2]
    wl = track[:, 3]
    total = wr + wl
    delta = np.roll(xy, -1, axis=0) - xy
    seg_len = np.linalg.norm(delta, axis=1)
    headings = np.arctan2(delta[:, 1], delta[:, 0])
    heading_delta = np.arctan2(
        np.sin(np.roll(headings, -1) - headings),
        np.cos(np.roll(headings, -1) - headings),
    )
    local_ds = np.maximum((seg_len + np.roll(seg_len, -1)) * 0.5, 1e-12)
    approx_curvature = np.abs(heading_delta) / local_ds
    width_jump = np.maximum(
        np.abs(np.roll(wr, -1) - wr),
        np.abs(np.roll(wl, -1) - wl),
    )

    rows = np.column_stack(
        (
            np.arange(len(track)),
            xy,
            wr,
            wl,
            total,
            total - float(safety_width),
            seg_len,
            width_jump,
            approx_curvature,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(
        path,
        rows,
        delimiter=",",
        fmt="%.9f",
        header=(
            "index,x,y,width_right,width_left,total_width,"
            "total_width_minus_safety,segment_length,width_jump,approx_curvature"
        ),
        comments="",
    )


def _configured_curvature_limit(input_path: str) -> float | None:
    """Read the same vehicle curvature limit used by the upstream optimizer."""
    config_file = Path(input_path) / "racecar_f110.ini"
    if not config_file.is_file():
        return None

    parser = configparser.ConfigParser()
    if not parser.read(config_file):
        return None

    try:
        veh_params = json.loads(parser.get("GENERAL_OPTIONS", "veh_params"))
        curvlim = float(veh_params["curvlim"])
    except (configparser.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read vehicle curvature limit from {config_file}: {exc}"
        ) from exc

    if not np.isfinite(curvlim) or curvlim <= 0.0:
        raise RuntimeError(
            f"Invalid vehicle curvature limit in {config_file}: {curvlim}"
        )
    return curvlim


def analyze_optimized_trajectory(
    trajectory: np.ndarray,
    curvature_limit: float | None,
) -> dict[str, Any]:
    """Inspect the final trajectory returned by the upstream optimizer.

    The upstream format is [s, x, y, psi, kappa, vx, ax].
    """
    traj = np.asarray(trajectory, dtype=float)
    if traj.ndim != 2 or traj.shape[1] < 5:
        raise RuntimeError(
            "Optimizer trajectory must have shape (N, >=5) with curvature in column 4, "
            f"got {traj.shape}."
        )
    if len(traj) < 2:
        raise RuntimeError("Optimizer trajectory must contain at least 2 points.")

    finite_rows = np.all(np.isfinite(traj[:, :5]), axis=1)
    abs_curvature = np.abs(traj[:, 4])
    finite_curvature = np.where(np.isfinite(abs_curvature), abs_curvature, -np.inf)
    max_curvature_index = int(np.argmax(finite_curvature))
    max_abs_curvature = float(finite_curvature[max_curvature_index])

    steps = np.linalg.norm(np.diff(traj[:, 1:3], axis=0), axis=1)
    min_step_index = int(np.argmin(steps))
    min_step = float(steps[min_step_index])

    return {
        "points": int(len(traj)),
        "nonfinite_indices": np.flatnonzero(~finite_rows).astype(int).tolist(),
        "max_abs_curvature": max_abs_curvature,
        "max_abs_curvature_index": max_curvature_index,
        "curvature_limit": curvature_limit,
        "min_step": min_step,
        "min_step_index": min_step_index,
    }


def _validate_fallback_result(result: Any, input_path: str, label: str) -> dict[str, Any]:
    if not isinstance(result, (tuple, list)) or not result:
        raise RuntimeError(f"{label}: optimizer returned an unexpected result object.")

    curvature_limit = _configured_curvature_limit(input_path)
    diag = analyze_optimized_trajectory(result[0], curvature_limit)

    if diag["nonfinite_indices"]:
        raise RuntimeError(
            f"{label}: fallback trajectory contains non-finite values at indices "
            f"{diag['nonfinite_indices'][:12]}."
        )
    if diag["min_step"] < 1e-6:
        raise RuntimeError(
            f"{label}: fallback trajectory contains a degenerate segment at "
            f"index {diag['min_step_index']} (step={diag['min_step']:.9f}m)."
        )

    if curvature_limit is not None:
        # Allow only a very small post-interpolation numerical overshoot.
        allowed = curvature_limit + max(0.02, curvature_limit * 0.02)
        if diag["max_abs_curvature"] > allowed:
            raise RuntimeError(
                f"{label}: fallback trajectory violates the configured curvature limit: "
                f"max_abs_curvature={diag['max_abs_curvature']:.3f}1/m"
                f"@{diag['max_abs_curvature_index']}, curvlim={curvature_limit:.3f}1/m "
                f"(acceptance limit={allowed:.3f}1/m)."
            )

    return diag


def _run_optimizer_once_with_diagnostics(
    *,
    tph: Any,
    trajectory_optimizer: Callable[..., Any],
    input_path: str,
    track_name: str,
    curv_opt_type: str,
    safety_width: float,
    plot: bool,
    diagnostics_dir: Path,
    label: str,
) -> Any:
    if curv_opt_type not in {"mincurv", "mincurv_iqp"}:
        return trajectory_optimizer(
            input_path=input_path,
            track_name=track_name,
            curv_opt_type=curv_opt_type,
            safety_width=safety_width,
            plot=plot,
        )

    original = tph.opt_min_curv.opt_min_curv
    solver_call = 0
    first_reftrack_written = False

    def diagnosed_opt_min_curv(*args: Any, **kwargs: Any) -> Any:
        nonlocal solver_call, first_reftrack_written
        solver_call += 1
        reftrack = kwargs.get("reftrack")
        w_veh = float(kwargs.get("w_veh", safety_width))

        if reftrack is not None and not first_reftrack_written:
            first_reftrack_written = True
            prepared_path = diagnostics_dir / f"{label}_prepared_reftrack.csv"
            write_reftrack_diagnostics(prepared_path, reftrack, w_veh)
            prepared_diag = analyze_reftrack(reftrack, w_veh)
            print(
                f"[RACELINE-DIAG] {label} prepared track: "
                f"{format_reftrack_diagnostics(prepared_diag)}"
            )

        try:
            return original(*args, **kwargs)
        except (ValueError, RuntimeError) as exc:
            if reftrack is None:
                raise

            failed_path = diagnostics_dir / f"{label}_failed_solver_call_{solver_call}.csv"
            write_reftrack_diagnostics(failed_path, reftrack, w_veh)
            diag = analyze_reftrack(reftrack, w_veh)
            detail = format_reftrack_diagnostics(diag)
            raise RuntimeError(
                f"{label}: minimum-curvature QP failed on solver call "
                f"{solver_call}: {exc}. Reftrack diagnostics: {detail}. "
                f"Per-point diagnostic CSV: {failed_path}"
            ) from exc

    tph.opt_min_curv.opt_min_curv = diagnosed_opt_min_curv
    try:
        return trajectory_optimizer(
            input_path=input_path,
            track_name=track_name,
            curv_opt_type=curv_opt_type,
            safety_width=safety_width,
            plot=plot,
        )
    finally:
        tph.opt_min_curv.opt_min_curv = original


def run_optimizer_with_diagnostics(
    *,
    tph: Any,
    trajectory_optimizer: Callable[..., Any],
    input_path: str,
    track_name: str,
    curv_opt_type: str,
    safety_width: float,
    plot: bool,
    diagnostics_dir: Path,
    label: str,
) -> Any:
    """Run an optimizer with per-iteration diagnostics and a guarded IQP fallback.

    ``mincurv_iqp`` can become infeasible only after several successful IQP
    iterations because every iteration moves and re-interpolates the reference
    track. If that happens, the failing iteration is dumped to CSV and a single
    non-iterative ``mincurv`` solve is attempted with the *same* safety width.
    The fallback is accepted only when its final trajectory is finite,
    non-degenerate, and respects the configured vehicle curvature limit within
    a small numerical tolerance. The safety constraint is never silently relaxed.
    """
    try:
        return _run_optimizer_once_with_diagnostics(
            tph=tph,
            trajectory_optimizer=trajectory_optimizer,
            input_path=input_path,
            track_name=track_name,
            curv_opt_type=curv_opt_type,
            safety_width=safety_width,
            plot=plot,
            diagnostics_dir=diagnostics_dir,
            label=label,
        )
    except (ValueError, RuntimeError) as iqp_exc:
        if curv_opt_type != "mincurv_iqp":
            raise

        print(f"[RACELINE-DIAG] {iqp_exc}")
        fallback_label = f"{label}_fallback_mincurv"
        print(
            f"[WARN] {label}: mincurv_iqp failed. "
            f"Retrying once with mincurv at the same safety_width={safety_width:.3f}m."
        )
        try:
            result = _run_optimizer_once_with_diagnostics(
                tph=tph,
                trajectory_optimizer=trajectory_optimizer,
                input_path=input_path,
                track_name=track_name,
                curv_opt_type="mincurv",
                safety_width=safety_width,
                plot=plot,
                diagnostics_dir=diagnostics_dir,
                label=fallback_label,
            )
        except (ValueError, RuntimeError) as fallback_exc:
            raise RuntimeError(
                f"{label}: both mincurv_iqp and the same-safety-width mincurv "
                f"fallback failed. IQP error: {iqp_exc} Fallback error: {fallback_exc}"
            ) from fallback_exc

        try:
            fallback_diag = _validate_fallback_result(
                result=result,
                input_path=input_path,
                label=fallback_label,
            )
        except RuntimeError as validation_exc:
            raise RuntimeError(
                f"{label}: mincurv_iqp failed and the mincurv fallback was rejected. "
                f"Fallback validation: {validation_exc} Original IQP error: {iqp_exc}"
            ) from validation_exc

        curvature_limit = fallback_diag["curvature_limit"]
        if curvature_limit is None:
            curvature_text = "curvlim=unavailable"
        else:
            curvature_text = (
                f"max_abs_curvature={fallback_diag['max_abs_curvature']:.3f}1/m, "
                f"curvlim={curvature_limit:.3f}1/m"
            )
        print(
            f"[WARN] {label}: mincurv fallback passed post-validation "
            f"({curvature_text}). Inspect the IQP failure CSV before using it."
        )
        return result
