from __future__ import annotations

import http.client
import json
import socket
import tempfile
import threading
import time
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

import cv2
import yaml

_MAX_UPLOAD = 64 * 1024 * 1024
_ALLOWED = {".yaml", ".yml", ".png", ".pgm", ".jpg", ".jpeg", ".json"}
_PROXY_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}
_MAP_REQUIRED_KEYS = {"image", "resolution", "origin"}


def _safe_name(name: str) -> str:
    normalized = name.replace("\\", "/").strip()
    path = Path(normalized)
    if not normalized or normalized in {".", ".."} or path.name != normalized:
        raise ValueError(f"폴더 경로가 포함된 파일명은 지원하지 않습니다: {name}")
    if path.suffix.lower() not in _ALLOWED:
        raise ValueError(f"허용되지 않는 파일입니다: {name}")
    return normalized


def _parse_multipart(body: bytes, content_type: str) -> list[tuple[str, bytes]]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("multipart/form-data boundary가 없습니다.")
    boundary_text = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary_text:
        raise ValueError("multipart/form-data boundary가 비어 있습니다.")
    boundary = boundary_text.encode("ascii", "strict")
    delimiter = b"--" + boundary
    files: list[tuple[str, bytes]] = []
    seen: set[str] = set()

    for raw_part in body.split(delimiter)[1:]:
        if raw_part.startswith(b"--"):
            break
        if raw_part.startswith(b"\r\n"):
            raw_part = raw_part[2:]
        if raw_part.endswith(b"\r\n"):
            raw_part = raw_part[:-2]
        if b"\r\n\r\n" not in raw_part:
            continue
        headers, data = raw_part.split(b"\r\n\r\n", 1)
        text = headers.decode("utf-8", "replace")
        disposition = next((line for line in text.split("\r\n") if line.lower().startswith("content-disposition:")), "")
        if "filename=" not in disposition:
            continue
        raw_name = disposition.split("filename=", 1)[1].split(";", 1)[0].strip().strip('"')
        name = _safe_name(raw_name)
        if name in seen:
            raise ValueError(f"같은 이름의 파일이 중복 업로드되었습니다: {name}")
        seen.add(name)
        files.append((name, data))

    if not files:
        raise ValueError("업로드된 파일이 없습니다.")
    return files


def _load_map_yaml_candidates(files: list[tuple[str, bytes]]) -> list[tuple[str, dict]]:
    candidates: list[tuple[str, dict]] = []
    for name, data in files:
        if Path(name).suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            parsed = yaml.safe_load(data.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError):
            continue
        if isinstance(parsed, dict) and _MAP_REQUIRED_KEYS.issubset(parsed):
            candidates.append((name, parsed))
    return candidates


def _validate_map_bundle(files: list[tuple[str, bytes]]) -> tuple[str, dict]:
    candidates = _load_map_yaml_candidates(files)
    if len(candidates) != 1:
        if not candidates:
            raise ValueError("image, resolution, origin을 포함한 맵 YAML 파일이 필요합니다.")
        raise ValueError("맵 YAML 후보가 여러 개입니다. 맵 YAML은 정확히 하나만 업로드하세요.")

    map_name, meta = candidates[0]
    resolution = meta.get("resolution")
    origin = meta.get("origin")
    if isinstance(resolution, bool) or not isinstance(resolution, (int, float)) or float(resolution) <= 0:
        raise ValueError("맵 YAML의 resolution은 0보다 큰 숫자여야 합니다.")
    if not isinstance(origin, (list, tuple)) or len(origin) < 3:
        raise ValueError("맵 YAML의 origin은 [x, y, yaw] 형식이어야 합니다.")
    try:
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in origin[:3]):
            raise ValueError
    except TypeError as exc:
        raise ValueError("맵 YAML의 origin은 숫자 [x, y, yaw] 형식이어야 합니다.") from exc

    image_value = str(meta.get("image", "")).replace("\\", "/")
    if not image_value or Path(image_value).name != image_value:
        raise ValueError("온라인 모드의 map YAML image 항목은 같은 폴더의 파일명만 사용해야 합니다.")
    image_name = _safe_name(image_value)
    uploaded = {name: data for name, data in files}
    image_data = uploaded.get(image_name)
    if image_data is None:
        raise ValueError(f"YAML이 참조하는 이미지 '{image_name}'도 함께 업로드해야 합니다.")
    if Path(image_name).suffix.lower() not in {".png", ".pgm", ".jpg", ".jpeg"}:
        raise ValueError(f"맵 이미지 형식을 지원하지 않습니다: {image_name}")

    import numpy as np
    decoded = cv2.imdecode(np.frombuffer(image_data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None or decoded.size == 0:
        raise ValueError(f"맵 이미지 '{image_name}'를 디코딩할 수 없습니다.")
    return map_name, meta


def _zip_project(root: Path) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".work" not in path.parts:
                zf.write(path, path.relative_to(root))
    return buf.getvalue()


def _online_page() -> bytes:
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>F1TENTH Online</title><style>body{font-family:system-ui;background:#101318;color:#e8edf2;max-width:760px;margin:60px auto;padding:20px}.drop{border:2px dashed #66717f;border-radius:14px;padding:70px 30px;text-align:center}.drop.over{border-color:#d7e8ff;background:#171d25}button{padding:10px 16px;margin:8px;border-radius:8px}#status{white-space:pre-wrap;color:#aab4c0}</style></head><body><h1>F1TENTH 레이스라인 온라인 서비스</h1><p>맵 YAML과 YAML이 참조하는 이미지(PGM/PNG 등)를 함께 드래그해서 놓으세요.</p><div id="drop" class="drop">파일을 여기에 드래그 앤 드롭<br><button onclick="pick.click()">파일 선택</button><input id="pick" type="file" multiple hidden></div><div id="status"></div><script>const d=document.querySelector('#drop'),p=document.querySelector('#pick'),s=document.querySelector('#status');['dragenter','dragover'].forEach(x=>d.addEventListener(x,e=>{e.preventDefault();d.classList.add('over')}));['dragleave','drop'].forEach(x=>d.addEventListener(x,e=>{e.preventDefault();d.classList.remove('over')}));d.addEventListener('drop',e=>upload(e.dataTransfer.files));p.onchange=()=>upload(p.files);async function upload(fs){let f=new FormData();for(const x of fs)f.append('files',x);s.textContent='업로드 및 검증 중...';let r=await fetch('/api/upload',{method:'POST',body:f}),j=await r.json();if(!r.ok){s.textContent=j.error;return}s.innerHTML=`업로드 및 검증 완료: ${j.map}<br><a href="${j.editor}" target="_blank"><button>편집기 열기</button></a><a href="${j.download}"><button>프로젝트 다운로드</button></a>`}</script></body></html>'''.encode("utf-8")


def _editor_route(path: str) -> tuple[str, str] | None:
    if not path.startswith("/editor/"):
        return None
    parts = path.split("/")
    if len(parts) < 3 or not parts[2]:
        return None
    key = parts[2]
    suffix = "/" + "/".join(parts[3:]) if len(parts) > 3 else "/"
    if suffix == "//":
        suffix = "/"
    return key, suffix


def _rewrite_editor_body(data: bytes, content_type: str) -> bytes:
    ctype = content_type.lower()
    if "text/html" in ctype:
        text = data.decode("utf-8")
        text = text.replace('src="/editor.js"', 'src="editor.js"')
        return text.encode("utf-8")
    if "javascript" in ctype:
        text = data.decode("utf-8")
        for quote_char in ("'", '"', '`'):
            text = text.replace(f"{quote_char}/api/", f"{quote_char}api/")
            text = text.replace(f"{quote_char}/map.png", f"{quote_char}map.png")
            text = text.replace(f"{quote_char}/editor.js", f"{quote_char}editor.js")
        return text.encode("utf-8")
    return data


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"편집기 서버가 {timeout:.1f}초 안에 시작되지 않았습니다: {last_error}")


def run_online_service(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    workspace = Path(tempfile.mkdtemp(prefix="raceline-online-"))
    projects: dict[str, tuple[Path, int]] = {}
    page = _online_page()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): print(f"[online] {self.address_string()} - {fmt % args}")

        def send_data(self, data: bytes, ctype: str, status=200, disposition: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if disposition: self.send_header("Content-Disposition", disposition)
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, obj, status=200):
            self.send_data(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def proxy_editor(self, key: str, backend_path: str) -> None:
            project = projects.get(key)
            if not project:
                self.send_json({"error": "project not found"}, 404); return
            _, editor_port = project
            parsed = urlparse(self.path)
            target = backend_path
            if parsed.query:
                target += "?" + parsed.query
            body = b""
            if self.command in {"POST", "PUT", "PATCH"}:
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _PROXY_HOP_HEADERS and k.lower() not in {"host", "content-length"}}
            if body: headers["Content-Length"] = str(len(body))
            conn = http.client.HTTPConnection("127.0.0.1", editor_port, timeout=300)
            try:
                conn.request(self.command, target, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                ctype = resp.getheader("Content-Type", "application/octet-stream")
                data = _rewrite_editor_body(data, ctype)
                self.send_response(resp.status)
                for header, value in resp.getheaders():
                    if header.lower() not in _PROXY_HOP_HEADERS and header.lower() not in {"content-length", "cache-control", "content-encoding"}:
                        self.send_header(header, value)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except (ConnectionError, OSError, http.client.HTTPException) as exc:
                self.send_json({"error": f"편집기 연결 실패: {exc}"}, 502)
            finally:
                conn.close()

        def do_GET(self):
            parsed = urlparse(self.path); path = parsed.path
            if path == "/":
                self.send_data(page, "text/html; charset=utf-8"); return
            if path.startswith("/download/"):
                key = path.rsplit("/", 1)[-1]; project = projects.get(key)
                if not project: self.send_json({"error":"project not found"}, 404); return
                root, _ = project
                self.send_data(_zip_project(root), "application/zip", disposition=f'attachment; filename="raceline-{key}.zip"'); return
            route = _editor_route(path)
            if route:
                key, suffix = route
                if key not in projects: self.send_json({"error":"project not found"}, 404); return
                if path == f"/editor/{key}":
                    self.send_response(302)
                    self.send_header("Location", f"/editor/{quote(key)}/")
                    self.end_headers(); return
                self.proxy_editor(key, suffix); return
            self.send_json({"error":"not found"}, 404)

        def do_POST(self):
            parsed = urlparse(self.path); path = parsed.path
            if path == "/api/upload":
                root: Path | None = None
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > _MAX_UPLOAD:
                        raise ValueError("업로드 크기는 64 MiB 이하여야 합니다.")
                    files = _parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))
                    map_name, _ = _validate_map_bundle(files)
                    key = next(tempfile._get_candidate_names()); root = workspace / key; root.mkdir()
                    for name, data in files:
                        (root / name).write_bytes(data)
                    map_yaml = root / map_name

                    from .editor_server import run_editor
                    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
                    editor_port = probe.server_port; probe.server_close()
                    thread = threading.Thread(target=run_editor, kwargs={"map_yaml":map_yaml,"host":"127.0.0.1","port":editor_port,"open_browser":False}, daemon=True)
                    thread.start()
                    _wait_for_port(editor_port)
                    if not thread.is_alive():
                        raise RuntimeError("편집기 서버가 시작 직후 종료되었습니다.")
                    projects[key] = (root, editor_port)
                    self.send_json({"ok":True,"map":map_name,"editor":f"/editor/{quote(key)}/","download":f"/download/{quote(key)}"})
                except Exception as exc:
                    if root is not None and root.is_dir():
                        import shutil
                        shutil.rmtree(root, ignore_errors=True)
                    self.send_json({"ok":False,"error":str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            route = _editor_route(path)
            if route:
                key, suffix = route
                if key not in projects:
                    self.send_json({"error":"project not found"}, 404); return
                self.proxy_editor(key, suffix); return
            self.send_json({"error":"not found"}, 404)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print(f"Online service: {url}\nTemporary workspace: {workspace}")
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
