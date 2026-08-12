from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from .core import generate_racelines
from .vendor import UPSTREAM_COMMIT, default_config_dir, ensure_vendor


def save_csv(path: Path, arr: np.ndarray, header: str) -> None:
    np.savetxt(path, arr, delimiter=",", header=header, comments="", fmt="%.9f")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    path = ensure_vendor(force=args.force)
    print(f"Vendor ready: {path}")
    print(f"Pinned commit: {UPSTREAM_COMMIT}")
    print(f"Default config: {default_config_dir(path)}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    failures = []
    print(f"Python: {sys.version.split()[0]}")
    print(f"Executable: {sys.executable}")
    print(f"Git: {shutil.which('git') or 'NOT FOUND'}")

    for module in ["numpy", "scipy", "cv2", "yaml", "skimage", "sklearn", "casadi", "quadprog", "trajectory_planning_helpers"]:
        try:
            m = importlib.import_module(module)
            version = getattr(m, "__version__", "(no __version__)")
            print(f"{module}: OK {version}")
        except Exception as exc:
            failures.append((module, str(exc)))
            print(f"{module}: FAIL {exc}")

    try:
        checkout = ensure_vendor()
        from .vendor import activate_optimizer_imports
        activate_optimizer_imports(checkout)
        from .compat import verify_tph_spline_approximation_compat
        verify_tph_spline_approximation_compat()
        print(f"Vendor: OK {checkout}")
        print("TPH/SciPy spline compatibility: OK")
    except Exception as exc:
        failures.append(("vendor/compat", str(exc)))
        print(f"Vendor/compat: FAIL {exc}")

    if failures:
        print("\nDoctor found problems:")
        for name, reason in failures:
            print(f"  - {name}: {reason}")
        return 1
    print("\nDoctor: all checks passed.")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from .editor_server import run_editor
    run_editor(map_yaml=args.map, profile_path=args.profile, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    map_yaml = args.map.resolve()
    out = args.output_dir.resolve() if args.output_dir else (map_yaml.parent / "raceline_offline").resolve()
    out.mkdir(parents=True, exist_ok=True)
    initial = tuple(args.initial_pose) if args.initial_pose else None

    if args.edit is None:
        result = generate_racelines(map_yaml, config_dir=args.config_dir, safety_width=args.safety_width, safety_width_sp=args.safety_width_sp, reverse=args.reverse, initial_position=initial, work_dir=out / ".work")
    else:
        from .edit_model import materialize_profile
        with materialize_profile(map_yaml, args.edit.resolve()) as edited_map:
            result = generate_racelines(edited_map.yaml_path, config_dir=args.config_dir, safety_width=args.safety_width, safety_width_sp=args.safety_width_sp, reverse=args.reverse, initial_position=initial, work_dir=out / ".work")

    save_csv(out / "centerline.csv", result.centerline_with_width, "x_m,y_m,width_right_m,width_left_m")
    save_csv(out / "raceline_iqp.csv", result.raceline_iqp, "s_m,x_m,y_m,psi_rad,kappa_radpm,vx_mps,ax_mps2")
    save_csv(out / "raceline_shortest.csv", result.raceline_shortest, "s_m,x_m,y_m,psi_rad,kappa_radpm,vx_mps,ax_mps2")
    save_csv(out / "ltpl.csv", result.ltpl, "x_ref_m,y_ref_m,width_right_m,width_left_m,x_normvec_m,y_normvec_m,alpha_m,s_racetraj_m,psi_racetraj_rad,kappa_racetraj_radpm,vx_racetraj_mps,ax_racetraj_mps2")
    save_csv(out / "bound_right.csv", result.bound_right, "x_m,y_m")
    save_csv(out / "bound_left.csv", result.bound_left, "x_m,y_m")

    summary = {
        "map": str(map_yaml),
        "optimizer_commit": UPSTREAM_COMMIT,
        "config_dir": str((args.config_dir or default_config_dir()).resolve()),
        "safety_width": args.safety_width,
        "safety_width_sp": args.safety_width_sp,
        "reverse": args.reverse,
        "estimated_lap_time_iqp_s": result.est_lap_time_iqp,
        "estimated_lap_time_shortest_s": result.est_lap_time_shortest,
        "outputs": {
            "centerline": str(out / "centerline.csv"),
            "raceline_iqp": str(out / "raceline_iqp.csv"),
            "raceline_shortest": str(out / "raceline_shortest.csv"),
            "ltpl": str(out / "ltpl.csv"),
            "bound_right": str(out / "bound_right.csv"),
            "bound_left": str(out / "bound_left.csv"),
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="raceline", description="ROS-free F1TENTH raceline generator.")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="Fetch the pinned optimizer/config source into the user cache.")
    bootstrap.add_argument("--force", action="store_true")
    bootstrap.set_defaults(func=cmd_bootstrap)

    doctor = sub.add_parser("doctor", help="Check Python dependencies, Git, and the pinned optimizer checkout.")
    doctor.set_defaults(func=cmd_doctor)

    edit = sub.add_parser("edit", help="Open a local browser editor for non-destructive occupancy-map edits.")
    edit.add_argument("--map", required=True, type=Path)
    edit.add_argument("--profile", type=Path, default=None)
    edit.add_argument("--host", default="127.0.0.1")
    edit.add_argument("--port", type=int, default=8765)
    edit.add_argument("--no-browser", action="store_true")
    edit.set_defaults(func=cmd_edit)

    generate = sub.add_parser("generate", help="Generate centerline and racelines from an existing map YAML/PNG.")
    generate.add_argument("--map", required=True, type=Path)
    generate.add_argument("--output-dir", type=Path, default=None)
    generate.add_argument("--edit", type=Path, default=None)
    generate.add_argument("--config-dir", type=Path, default=None)
    generate.add_argument("--safety-width", type=float, default=0.4)
    generate.add_argument("--safety-width-sp", type=float, default=0.35)
    generate.add_argument("--reverse", action="store_true")
    generate.add_argument("--initial-pose", nargs=3, type=float, metavar=("X", "Y", "YAW"))
    generate.set_defaults(func=cmd_generate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))
