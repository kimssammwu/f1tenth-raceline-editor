from pathlib import Path
import tomllib


def test_tph_080_is_pinned_to_upstream_git_commit() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "trajectory-planning-helpers==0.80" in data["project"]["dependencies"]

    source = data["tool"]["uv"]["sources"]["trajectory-planning-helpers"]
    assert source["git"] == "https://github.com/TUMFTM/trajectory_planning_helpers.git"
    assert source["rev"] == "aa950f6045680366b789dbb855db8d59d54b1db5"
