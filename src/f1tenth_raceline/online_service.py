from __future__ import annotations

import http.client
import json
import tempfile
import threading
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

_MAX_UPLOAD = 64 * 1024 * 1024
_ALLOWED = {".yaml", ".yml", ".png", ".pgm", ".jpg", ".jpeg", ".json"}
_PROXY_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    if not name or name in {".", ".."} or Path(name).suffix.lower() not in _ALLOWED:
        raise ValueError(f"허용되지 않는 파일입니다: {name}")
    return name


def _parse_multipart(body: bytes, content_type: str) -> list[tuple[str, bytes]]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("multipart/form-data boundary가 없습니다.")
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    files = []
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        headers, data = part.split(b"\r\n\r\n", 1)
        data = data.rstrip(b"\r\n-")
        text = headers.decode("utf-8", "replace")
        if "filename=" not in text:
            continue
        raw = text.split("filename=", 1)[1].split("\r\n", 1)[0].strip().strip('"')
        files.append((_safe_name(raw), data))
    return files


def _zip_project(root: Path) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".work" not in path.parts:
                zf.write(path, path.relative_to(root))
    return buf.getvalue()


def _online_page() -> bytes:
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>F1TENTH Online</title><style>body{font-family:system-ui;background:#101318;color:#e8edf2;max-width:760px;margin:60px auto;padding:20px}.drop{border:2px dashed #66717f;border-radius:14px;padding:70px 30px;text-align:center}.drop.over{border-color:#d7e8ff;background:#171d25}button{padding:10px 16px;margin:8px;border-radius:8px}#status{white-space:pre-wrap;color:#aab4c0}</style></head><body><h1>F1TENTH 레이스라인 온라인 서비스</h1><p>맵 YAML과 YAML이 참조하는 이미지(PGM/PNG 등)를 함께 드래그해서 놓으세요.</p><div id="drop" class="drop">파일을 여기에 드래그 앤 드롭<br><button onclick="pick.click()">파일 선택</button><input id="pick" type="file" multiple hidden></div><div id="status"></div><script>const d=document.querySelector('#drop'),p=document.querySelector('#pick'),s=document.querySelector('#status');['dragenter','dragover'].forEach(x=>d.addEventListener(x,e=>{e.preventDefault();d.classList.add('over')}));['dragleave','drop'].forEach(x=>d.addEventListener(x,e=>{e.preventDefault();d.classList.remove('over')}));d.addEventListener('drop',e=>upload(e.dataTransfer.files));p.onchange=()=>upload(p.files);async function upload(fs){let f=new FormData();for(const x of fs)f.append('files',x);s.textContent='업로드 중...';let r=await fetch('/api/upload',{method:'POST',body:f}),j=await r.json();if(!r.ok){s.textContent=j.error;return}s.innerHTML=`업로드 완료: ${j.map}<br><a href="${j.editor}" target="_blank"><button>편집기 열기</button></a><a href="${j.download}"><button>프로젝트 다운로드</button></a>`}</script></body></html>'''.encode("utf-8")


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for item in cookie_header.split(";"):
        key, sep, value = item.strip().partition("=")
        if sep and key == name:
            return value
    return None


def run_online_service(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    workspace = Path(tempfile.mkdtemp(prefix="raceline-online-"))
    projects: dict[str, tuple[Path, int]] = {}
    page = _online_page()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args): print(f"[online] {self.address_string()} - {fmt % args}")

        def send_data(self, data: bytes, ctype: str, status=200, disposition: str | None = None, extra_headers: dict[str, str] | None = None):
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
            if disposition: self.send_header("Content-Disposition", disposition)
            for key, value in (extra_headers or {}).items(): self.send_header(key, value)
            self.end_headers(); self.wfile.write(data)

        def send_json(self, obj, status=200): self.send_data(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def project_key(self) -> str | None:
            path = urlparse(self.path).path
            if path.startswith("/editor/"):
                parts = path.split("/")
                if len(parts) > 2 and parts[2] in projects:
                    return parts[2]
            return _cookie_value(self.headers.get("Cookie", ""), "raceline_project")

        def proxy_editor(self, key: str, backend_path: str | None = None) -> None:
            project = projects.get(key)
            if not project:
                self.send_json({"error": "project not found"}, 404); return
            _, editor_port = project
            parsed = urlparse(self.path)
            target = backend_path if backend_path is not None else parsed.path
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
                resp = conn.getresponse(); data = resp.read()
                self.send_response(resp.status)
                for header, value in resp.getheaders():
                    if header.lower() not in _PROXY_HOP_HEADERS and header.lower() != "content-length": self.send_header(header, value)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers(); self.wfile.write(data)
            except (ConnectionError, OSError, http.client.HTTPException) as exc:
                self.send_json({"error": f"편집기 연결 실패: {exc}"}, 502)
            finally:
                conn.close()

        def do_GET(self):
            parsed = urlparse(self.path); path = parsed.path
            if path == "/": self.send_data(page, "text/html; charset=utf-8"); return
            if path.startswith("/download/"):
                key = path.rsplit("/", 1)[-1]; project = projects.get(key)
                if not project: self.send_json({"error":"project not found"}, 404); return
                root, _ = project; self.send_data(_zip_project(root), "application/zip", disposition=f'attachment; filename="raceline-{key}.zip"'); return
            if path.startswith("/editor/"):
                parts = path.split("/"); key = parts[2] if len(parts) > 2 else ""
                if key not in projects: self.send_json({"error":"project not found"}, 404); return
                suffix = "/" + "/".join(parts[3:]) if len(parts) > 3 else "/"
                if suffix == "//": suffix = "/"
                if parsed.query: suffix += "?" + parsed.query
                self.send_response(302); self.send_header("Location", f"/editor/{quote(key)}/"); self.send_header("Set-Cookie", f"raceline_project={key}; Path=/; SameSite=Lax"); self.end_headers(); return
            key = self.project_key()
            if key and path in {"/editor.js", "/map.png", "/index.html"}: self.proxy_editor(key); return
            if key and path.startswith("/api/"): self.proxy_editor(key); return
            self.send_json({"error":"not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/upload":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > _MAX_UPLOAD: raise ValueError("업로드 크기는 64 MiB 이하여야 합니다.")
                    files = _parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))
                    yamls = [n for n,_ in files if Path(n).suffix.lower() in {".yaml", ".yml"}]
                    if len(yamls) != 1: raise ValueError("맵 YAML 파일을 정확히 하나 포함해야 합니다.")
                    key = next(tempfile._get_candidate_names()); root = workspace / key; root.mkdir()
                    for name,data in files: (root / name).write_bytes(data)
                    map_yaml = root / yamls[0]
                    import yaml
                    meta = yaml.safe_load(map_yaml.read_text(encoding="utf-8")) or {}; image = _safe_name(str(meta.get("image", "")))
                    if not (root / image).is_file(): raise ValueError(f"YAML이 참조하는 이미지 '{image}'도 함께 업로드해야 합니다.")
                    from .editor_server import run_editor
                    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler); editor_port = probe.server_port; probe.server_close()
                    projects[key] = (root, editor_port)
                    threading.Thread(target=run_editor, kwargs={"map_yaml":map_yaml,"host":"127.0.0.1","port":editor_port,"open_browser":False}, daemon=True).start()
                    self.send_json({"ok":True,"map":yamls[0],"editor":f"/editor/{quote(key)}/","download":f"/download/{quote(key)}"})
                except Exception as exc: self.send_json({"ok":False,"error":str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            key = self.project_key()
            if key and path.startswith("/api/"): self.proxy_editor(key); return
            self.send_json({"error":"not found"}, 404)

    server = ThreadingHTTPServer((host, port), Handler); url = f"http://{host}:{server.server_port}"; print(f"Online service: {url}\nTemporary workspace: {workspace}")
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
