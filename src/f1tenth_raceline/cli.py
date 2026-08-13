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
    path = ensure_vendor(force=args.force); print(f"Vendor ready: {path}\nPinned commit: {UPSTREAM_COMMIT}\nDefault config: {default_config_dir(path)}"); return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    failures = []; print(f"Python: {sys.version.split()[0]}\nExecutable: {sys.executable}\nGit: {shutil.which('git') or 'NOT FOUND'}")
    for module in ["numpy", "scipy", "cv2", "yaml", "skimage", "sklearn", "casadi", "quadprog", "trajectory_planning_helpers"]:
        try: m = importlib.import_module(module); print(f"{module}: OK {getattr(m, '__version__', '(no __version__)')}")
        except Exception as exc: failures.append((module, str(exc))); print(f"{module}: FAIL {exc}")
    try:
        checkout = ensure_vendor(); from .vendor import activate_optimizer_imports; activate_optimizer_imports(checkout); from .compat import verify_tph_spline_approximation_compat; verify_tph_spline_approximation_compat(); print(f"Vendor: OK {checkout}\nTPH/SciPy spline compatibility: OK")
    except Exception as exc: failures.append(("vendor/compat", str(exc))); print(f"Vendor/compat: FAIL {exc}")
    if failures:
        print("\nDoctor found problems:"); [print(f"  - {n}: {r}") for n,r in failures]; return 1
    print("\nDoctor: all checks passed."); return 0


def cmd_edit(args: argparse.Namespace) -> int:
    if args.online_service:
        if args.map is not None: raise SystemExit("--online-service 모드에서는 --map을 지정하지 마세요. 브라우저에서 업로드합니다.")
        from .online_recovery import install_online_optimizer_recovery
        install_online_optimizer_recovery()
        from .online_service import run_online_service
        run_online_service(host=args.host, port=args.port, open_browser=not args.no_browser); return 0
    if args.map is None: raise SystemExit("edit에는 --map이 필요합니다. 온라인 모드는 --online-service를 사용하세요.")
    from .editor_server import run_editor
    run_editor(map_yaml=args.map, profile_path=args.profile, sector_profile_path=args.sector_profile, raceline_dir=args.raceline_dir, host=args.host, port=args.port, open_browser=not args.no_browser); return 0


def cmd_sectors(args: argparse.Namespace) -> int:
    from .sectors import export_sector_files, load_raceline_csv, load_sector_profile
    map_yaml=args.map.resolve(); output_dir=args.raceline_dir.resolve() if args.raceline_dir else (map_yaml.parent/"output").resolve(); profile_path=args.profile.resolve() if args.profile else (map_yaml.parent/"edit"/"sectors.json").resolve(); raceline=load_raceline_csv(output_dir/"raceline_iqp.csv"); profile=load_sector_profile(profile_path,raceline); exported=export_sector_files(map_dir=output_dir,profile_path=profile_path,raceline=raceline,profile=profile); print(f"Sector profile: {exported.profile_path}\nSpeed sectors: {exported.speed_yaml_path}\nOvertaking sectors: {exported.ot_yaml_path}"); [print(f"[{w['severity'].upper()}] {w['message']}") for w in exported.warnings]; return 0


def _write_outputs(out: Path, result) -> None:
    save_csv(out/"centerline.csv",result.centerline_with_width,"x_m,y_m,width_right_m,width_left_m"); save_csv(out/"raceline_iqp.csv",result.raceline_iqp,"s_m,x_m,y_m,psi_rad,kappa_radpm,vx_mps,ax_mps2"); save_csv(out/"raceline_shortest.csv",result.raceline_shortest,"s_m,x_m,y_m,psi_rad,kappa_radpm,vx_mps,ax_mps2"); save_csv(out/"ltpl.csv",result.ltpl,"x_ref_m,y_ref_m,width_right_m,width_left_m,x_normvec_m,y_normvec_m,alpha_m,s_racetraj_m,psi_racetraj_rad,kappa_racetraj_radpm,vx_racetraj_mps,ax_racetraj_mps2"); save_csv(out/"bound_right.csv",result.bound_right,"x_m,y_m"); save_csv(out/"bound_left.csv",result.bound_left,"x_m,y_m")


def cmd_generate(args: argparse.Namespace) -> int:
    map_yaml=args.map.resolve(); out=args.output_dir.resolve() if args.output_dir else (map_yaml.parent/"output").resolve(); out.mkdir(parents=True,exist_ok=True); initial=tuple(args.initial_pose) if args.initial_pose else None; kwargs=dict(config_dir=args.config_dir,safety_width=args.safety_width,safety_width_sp=args.safety_width_sp,reverse=args.reverse,initial_position=initial,work_dir=out/".work")
    if args.edit is None: result=generate_racelines(map_yaml,**kwargs)
    else:
        from .edit_model import materialize_profile
        with materialize_profile(map_yaml,args.edit.resolve()) as edited_map: result=generate_racelines(edited_map.yaml_path,**kwargs)
    _write_outputs(out,result); from .upstream_exports import export_upstream_waypoint_json; global_waypoints,ltpl_waypoints=export_upstream_waypoint_json(out,result); summary={"map":str(map_yaml),"optimizer_commit":UPSTREAM_COMMIT,"config_dir":str((args.config_dir or default_config_dir()).resolve()),"safety_width":args.safety_width,"safety_width_sp":args.safety_width_sp,"reverse":args.reverse,"estimated_lap_time_iqp_s":result.est_lap_time_iqp,"estimated_lap_time_shortest_s":result.est_lap_time_shortest,"outputs":{"centerline":str(out/"centerline.csv"),"raceline_iqp":str(out/"raceline_iqp.csv"),"raceline_shortest":str(out/"raceline_shortest.csv"),"ltpl":str(out/"ltpl.csv"),"bound_right":str(out/"bound_right.csv"),"bound_left":str(out/"bound_left.csv"),"global_waypoints":str(global_waypoints),"ltpl_waypoints":str(ltpl_waypoints)}}; (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); print(json.dumps(summary,indent=2)); return 0


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="raceline",description="ROS-free F1TENTH raceline generator."); sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("bootstrap",help="Fetch pinned optimizer/config source."); p.add_argument("--force",action="store_true"); p.set_defaults(func=cmd_bootstrap)
    p=sub.add_parser("doctor",help="Check dependencies and optimizer checkout."); p.set_defaults(func=cmd_doctor)
    p=sub.add_parser("edit",help="Open browser editor, or drag-and-drop online service."); p.add_argument("--map",type=Path); p.add_argument("--online-service",action="store_true",help="Start upload/download web service; map is uploaded in browser."); p.add_argument("--profile",type=Path); p.add_argument("--sector-profile",type=Path); p.add_argument("--raceline-dir",type=Path,help="Generated output directory. Default: <map-dir>/output"); p.add_argument("--host",default="127.0.0.1"); p.add_argument("--port",type=int,default=8765); p.add_argument("--no-browser",action="store_true"); p.set_defaults(func=cmd_edit)
    p=sub.add_parser("sectors",help="Validate/export ROS-compatible sector YAML."); p.add_argument("--map",required=True,type=Path); p.add_argument("--profile",type=Path); p.add_argument("--raceline-dir",type=Path); p.set_defaults(func=cmd_sectors)
    p=sub.add_parser("generate",help="Generate centerline/racelines and original-stack waypoint JSON."); p.add_argument("--map",required=True,type=Path); p.add_argument("--output-dir",type=Path); p.add_argument("--edit",type=Path); p.add_argument("--config-dir",type=Path); p.add_argument("--safety-width",type=float,default=0.4); p.add_argument("--safety-width-sp",type=float,default=0.35); p.add_argument("--reverse",action="store_true"); p.add_argument("--initial-pose",nargs=3,type=float,metavar=("X","Y","YAW")); p.set_defaults(func=cmd_generate); return parser


def main() -> None:
    args=build_parser().parse_args(); raise SystemExit(args.func(args))
