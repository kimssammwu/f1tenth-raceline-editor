from __future__ import annotations

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
        "too_narrow_indices": np.flatnonzero(too_narrow).astype(int).tolist(),
        "duplicate_indices": np.flatnonzero(duplicate_like).astype(int).tolist(),
        "min_right_width": float(np.nanmin(wr)),
        "min_right_width_index": _argmin(wr),
        "min_left_width": float(np.nanmin(wl)),
        "min_left_width_index": _argmin(wl),
        "min_total_width": float(np.nanmin(total)),
        "min_total_width_index": _argmin(total),
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
    """Run the optimizer and annotate min-curvature QP failures with the exact reftrack.

    TPH's IQP handler repeatedly calls ``opt_min_curv`` while moving/interpolating
    the reference track. A QP can therefore become infeasible only after several
    successful IQP iterations. Temporarily wrapping ``opt_min_curv`` lets us dump
    the *actual iteration input* that caused quadprog to fail instead of only the
    original map centerline.
    """
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
