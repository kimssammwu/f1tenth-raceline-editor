from pathlib import Path

import pytest

from f1tenth_raceline.cli import build_parser
from f1tenth_raceline.online_service import (
    _editor_route,
    _online_page,
    _parse_multipart,
    _rewrite_editor_body,
    _safe_name,
)


def test_online_service_cli_does_not_require_map() -> None:
    args = build_parser().parse_args(["edit", "--online-service", "--no-browser"])
    assert args.online_service is True
    assert args.map is None


def test_safe_upload_names_reject_paths_and_unknown_extensions() -> None:
    assert _safe_name("nested/map.yaml") == "map.yaml"
    assert _safe_name("track.pgm") == "track.pgm"
    with pytest.raises(ValueError):
        _safe_name("payload.py")


def test_parse_multiple_drag_drop_files() -> None:
    boundary = "raceline-test"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"map.yaml\"\r\n\r\nimage: map.png\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"map.png\"\r\n\r\nPNGDATA\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    files = _parse_multipart(body, f"multipart/form-data; boundary={boundary}")
    assert [name for name, _ in files] == ["map.yaml", "map.png"]


def test_online_page_is_utf8_and_uses_same_origin_urls() -> None:
    page = _online_page().decode("utf-8")
    assert "F1TENTH 레이스라인 온라인 서비스" in page
    assert "127.0.0.1" not in page
    assert "fetch('/api/upload'" in page


def test_editor_route_is_project_scoped() -> None:
    assert _editor_route("/editor/abc/") == ("abc", "/")
    assert _editor_route("/editor/abc/api/save") == ("abc", "/api/save")
    assert _editor_route("/editor/xyz/map.png") == ("xyz", "/map.png")
    assert _editor_route("/api/save") is None


def test_editor_html_rewrites_script_to_project_relative_url() -> None:
    body = b'<html><script src="/editor.js"></script></html>'
    result = _rewrite_editor_body(body, "text/html; charset=utf-8").decode()
    assert 'src="editor.js"' in result
    assert 'src="/editor.js"' not in result


def test_editor_javascript_rewrites_root_api_and_map_urls() -> None:
    body = b'''fetch('/api/save'); fetch("/api/sectors"); img.src='/map.png';'''
    result = _rewrite_editor_body(body, "application/javascript").decode()
    assert "fetch('api/save')" in result
    assert 'fetch("api/sectors")' in result
    assert "img.src='map.png'" in result
    assert "'/api/" not in result
    assert "'/map.png" not in result


def test_two_projects_keep_distinct_editor_routes() -> None:
    assert _editor_route("/editor/project-a/api/save") == ("project-a", "/api/save")
    assert _editor_route("/editor/project-b/api/save") == ("project-b", "/api/save")
