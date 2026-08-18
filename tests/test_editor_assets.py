from pathlib import Path


def test_sector_editor_has_safety_guards_and_korean_ui() -> None:
    root = Path(__file__).parents[1] / "src/f1tenth_raceline/web"
    html = (root / "index.html").read_text()
    js = (root / "editor.js").read_text()
    assert '<script src="/editor.js"></script>' in html
    assert '<html lang="ko">' in html
    assert "저장 + 레이스라인 재생성" in html
    assert "bestD <= 35*35 ? best : null" in js
    assert "!data.shortest_available" in js
    assert "추월 섹터" in js


def test_editor_regeneration_is_wired_end_to_end() -> None:
    root = Path(__file__).parents[1]
    js = (root / "src/f1tenth_raceline/web/editor.js").read_text()
    server = (root / "src/f1tenth_raceline/editor_server.py").read_text()
    assert "'/api/regenerate-raceline'" in js
    assert 'path == "/api/regenerate-raceline"' in server
    assert "save_profile(state.profile_path" in server
    assert "_regenerate_racelines(state, progress=" in server
    assert "sectors = _sector_payload(state)" in server
    assert "materialize_profile(state.map_yaml, state.profile_path)" in server


def test_editor_exposes_progress_and_output_download() -> None:
    root = Path(__file__).parents[1]
    html = (root / "src/f1tenth_raceline/web/index.html").read_text()
    server = (root / "src/f1tenth_raceline/editor_server.py").read_text()
    assert 'id="downloadOutputBtn"' in html
    assert 'id="generationProgress"' in html
    assert "api/regeneration-status" in html
    assert "api/output.zip" in html
    assert 'path == "/api/regeneration-status"' in server
    assert 'path == "/api/output.zip"' in server
