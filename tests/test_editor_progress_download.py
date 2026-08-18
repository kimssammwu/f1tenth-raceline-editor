from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from f1tenth_raceline.editor_server import _zip_output_dir


def test_output_zip_contains_public_outputs_and_excludes_work(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "raceline_iqp.csv").write_text("s_m,x_m,y_m\n", encoding="utf-8")
    (output / "global_waypoints.json").write_text("{}", encoding="utf-8")
    (output / "speed_scaling.yaml").write_text("speed_scaling: []\n", encoding="utf-8")
    work = output / ".work"
    work.mkdir()
    (work / "diagnostic.csv").write_text("secret\n", encoding="utf-8")

    payload = _zip_output_dir(output)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
    assert "raceline_iqp.csv" in names
    assert "global_waypoints.json" in names
    assert "speed_scaling.yaml" in names
    assert not any(".work" in name for name in names)


def test_output_zip_requires_generated_files(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(FileNotFoundError):
        _zip_output_dir(output)


def test_editor_html_exposes_progress_and_download_controls() -> None:
    html = (Path(__file__).parents[1] / "src" / "f1tenth_raceline" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="downloadOutputBtn"' in html
    assert 'id="generationProgress"' in html
    assert "api/regeneration-status" in html
    assert "api/output.zip" in html
