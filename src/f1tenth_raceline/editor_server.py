from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2

from .core import extract_centerline, smooth_centerline
from .edit_model import (
    apply_profile,
    load_base_image,
    load_profile,
    normalize_profile,
    save_profile,
)


@dataclass
class EditorState:
    map_yaml: Path
    profile_path: Path
    base_image: object
    map_data: dict
    image_path: Path


def _json_bytes(data: object) -> bytes:
    return json.dumps(data).encode("utf-8")


def _preview_centerline(state: EditorState, profile: dict) -> list[list[float]]:
    normalized = normalize_profile(profile, state.map_yaml, state.base_image)
    edited = apply_profile(state.base_image, normalized)

    # Keep preview preprocessing exactly aligned with core.generate_racelines().
    filtered_map = cv2.flip(edited, 0)
    from skimage.morphology import skeletonize

    skeleton = skeletonize(filtered_map, method="lee")
    resolution = float(state.map_data["resolution"])
    centerline = extract_centerline(
        skeleton=skeleton,
        cent_length=0.0,
        map_resolution=resolution,
        map_editor_mode=True,
    )
    centerline = smooth_centerline(centerline)

    height = edited.shape[0]
    raw = centerline.copy()
    raw[:, 1] = (height - 1) - raw[:, 1]

    # Limit browser payload for very dense contours while preserving shape.
    stride = max(1, len(raw) // 2500)
    return [[float(x), float(y)] for x, y in raw[::stride]]


def run_editor(
    map_yaml: Path,
    profile_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    map_yaml = map_yaml.resolve()
    base_image, map_data, image_path = load_base_image(map_yaml)
    profile_path = (
        profile_path.resolve()
        if profile_path
        else (map_yaml.parent / "edit" / "map_edit.json").resolve()
    )
    state = EditorState(
        map_yaml=map_yaml,
        profile_path=profile_path,
        base_image=base_image,
        map_data=map_data,
        image_path=image_path,
    )

    web_path = Path(__file__).with_name("web") / "index.html"
    html = web_path.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "F1TenthRacelineEditor/1.0"

        def log_message(self, fmt: str, *args) -> None:
            print(f"[editor] {self.address_string()} - {fmt % args}")

        def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data: object, status: int = 200) -> None:
            self.send_bytes(_json_bytes(data), "application/json; charset=utf-8", status)

        def read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self.send_bytes(html, "text/html; charset=utf-8")
                return
            if path == "/map.png":
                ok, encoded = cv2.imencode(".png", state.base_image)
                if not ok:
                    self.send_json({"error": "could not encode map"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self.send_bytes(encoded.tobytes(), "image/png")
                return
            if path == "/api/state":
                profile = load_profile(state.profile_path, state.map_yaml, state.base_image)
                h, w = state.base_image.shape[:2]
                self.send_json(
                    {
                        "map": str(state.map_yaml),
                        "profile": str(state.profile_path),
                        "width": int(w),
                        "height": int(h),
                        "operations": profile["operations"],
                        "generate_command": (
                            f'uv run raceline generate --map "{state.map_yaml}" '
                            f'--edit "{state.profile_path}"'
                        ),
                    }
                )
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self.read_json()
                if path == "/api/save":
                    saved = save_profile(
                        state.profile_path,
                        payload,
                        state.map_yaml,
                        state.base_image,
                    )
                    self.send_json({"ok": True, "operations": len(saved["operations"])})
                    return
                if path == "/api/preview-centerline":
                    points = _preview_centerline(state, payload)
                    self.send_json({"ok": True, "points": points})
                    return
                if path == "/api/shutdown":
                    self.send_json({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print(f"Map editor: {url}")
    print(f"Map: {map_yaml}")
    print(f"Edit profile: {profile_path}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
