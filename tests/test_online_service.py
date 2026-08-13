from pathlib import Path

import pytest

from f1tenth_raceline.cli import build_parser
from f1tenth_raceline.online_service import _parse_multipart, _safe_name


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
