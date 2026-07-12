from __future__ import annotations

import argparse
import json
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _preview_text(text: str, limit: int = 600) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]


def _json_preview(payload: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload)
    return _preview_text(text, limit=limit)


def _log(log_file: Path, line: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    formatted = f"[{ts}] {line}"
    print(formatted)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(formatted + "\n")


def _is_valid_pptx(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pptx":
        return False
    if path.stat().st_size < 128:
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
    except Exception:
        return False
    return (
        "[Content_Types].xml" in names
        and "ppt/presentation.xml" in names
        and any(name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names)
    )


class PresentonProbe:
    def __init__(
        self,
        base_url: str,
        timeout: int,
        output_dir: Path,
        log_file: Path,
        username: str = "",
        password: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_file
        self.username = username
        self.password = password
        self.token: str = ""
        self.session = requests.Session()

    def login(self) -> None:
        if not self.username or not self.password:
            return
        payload = {"username": self.username, "password": self.password}
        response = self.request("POST", "/api/v1/auth/login", json_body=payload)
        data = response.json() if response.content else {}
        token = ""
        if isinstance(data, dict):
            token = str(data.get("access_token") or data.get("token") or data.get("accessToken") or "")
        if token:
            self.token = token
            _log(self.log_file, "AUTH token acquired")
        else:
            raise RuntimeError(f"Login succeeded but no token found: {data}")

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        stream: bool = False,
    ) -> requests.Response:
        url = self.base_url + path
        start = time.monotonic()
        body_preview = _json_preview(json_body) if json_body is not None else ""
        _log(self.log_file, f"REQUEST {method.upper()} {path} timeout={timeout or self.timeout}s body={body_preview}")

        response = self.session.request(
            method=method.upper(),
            url=url,
            json=json_body,
            headers=({"Authorization": f"Bearer {self.token}"} if self.token else None),
            timeout=(timeout or self.timeout),
            stream=stream,
        )

        elapsed = round(time.monotonic() - start, 3)
        text_preview = ""
        if not stream:
            try:
                text_preview = _preview_text(response.text)
            except Exception:
                text_preview = "<unreadable>"
        _log(
            self.log_file,
            f"RESPONSE {method.upper()} {path} status={response.status_code} elapsed={elapsed}s body={text_preview}",
        )
        response.raise_for_status()
        return response

    def run(self) -> Dict[str, Any]:
        run_started = time.monotonic()
        self.login()

        create_payload = {
            "title": "Direct Presenton Probe",
            "content": "Slide 1: Hello from direct Presenton API probe. Slide 2: This run validates Create -> Prepare -> Generate -> Export.",
            "language": "English",
            "template": "general",
            "template_name": "general",
        }
        create_response = self.request("POST", "/api/v1/ppt/presentation/create", json_body=create_payload)
        create_data = create_response.json()
        presentation_id = create_data.get("id") or create_data.get("presentation_id")
        if not presentation_id:
            raise RuntimeError(f"No presentation id in create response: {create_data}")

        layout_payload = {
            "name": "general",
            "slides": [
                    {
                        "id": "slide-1",
                        "title": "Executive Summary",
                        "subtitle": "Summary",
                        "content": [],
                        "json_schema": {"type": "object", "properties": {}},
                    }
            ],
            "theme": "default",
            "icon_weight": "bold",
            "include_title_slide": True,
            "include_table_of_contents": False,
        }
        outlines = [
            {"title": "Probe Overview", "content": "Direct API path verification"},
            {"title": "Probe Result", "content": "Create Prepare Generate Export evidence"},
        ]
        prepare_payload = {
            "presentation_id": presentation_id,
            "outlines": outlines,
            "layout": layout_payload,
        }
        self.request("POST", "/api/v1/ppt/presentation/prepare", json_body=prepare_payload)

        generate_payload = {
            "content": create_payload["content"],
            "n_slides": 2,
            "language": "English",
            "template": "general",
            "instructions": "Keep slides concise.",
            "export_as": "pptx",
            "include_title_slide": True,
            "include_table_of_contents": False,
            "web_search": False,
            "tone": "default",
            "verbosity": "standard",
            "presentation_id": presentation_id,
        }
        generate_response = self.request("POST", "/api/v1/ppt/presentation/generate/async", json_body=generate_payload)
        generate_data = generate_response.json()
        task_id = generate_data.get("id")
        if not task_id:
            raise RuntimeError(f"No task id in generate response: {generate_data}")

        terminal_payload: Optional[Dict[str, Any]] = None
        for poll in range(1, 301):
            status_response = self.request("GET", f"/api/v1/ppt/presentation/status/{task_id}", timeout=15)
            status_payload = status_response.json()
            status = str(status_payload.get("status") or "").lower()
            _log(self.log_file, f"POLL task={task_id} idx={poll} status={status}")
            if status in {"completed", "succeeded", "success"}:
                terminal_payload = status_payload
                break
            if status in {"failed", "error"}:
                raise RuntimeError(f"Generate failed: {status_payload}")
            time.sleep(2)

        if terminal_payload is None:
            raise RuntimeError(f"Generate did not complete in polling window for task {task_id}")

        data = terminal_payload.get("data") if isinstance(terminal_payload.get("data"), dict) else {}
        export_path = str(data.get("path") or "").strip()
        if not export_path:
            raise RuntimeError(f"No export path in terminal payload: {terminal_payload}")

        if export_path.startswith("http://") or export_path.startswith("https://"):
            export_url = export_path
        else:
            export_url = f"{self.base_url}{export_path if export_path.startswith('/') else '/' + export_path}"

        target_name = f"presenton-direct-probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pptx"
        target_file = self.output_dir / target_name
        export_response = self.request("GET", export_url.replace(self.base_url, ""), timeout=120, stream=True)
        with target_file.open("wb") as handle:
            for chunk in export_response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    handle.write(chunk)
        _log(self.log_file, f"EXPORT saved={target_file} size={target_file.stat().st_size}")

        if not _is_valid_pptx(target_file):
            raise RuntimeError(f"Downloaded PPTX is invalid: {target_file}")

        elapsed = round(time.monotonic() - run_started, 3)
        result = {
            "status": "success",
            "base_url": self.base_url,
            "presentation_id": presentation_id,
            "task_id": task_id,
            "export_source": export_path,
            "export_file": str(target_file),
            "elapsed_seconds": elapsed,
            "log_file": str(self.log_file),
        }
        _log(self.log_file, f"RESULT {json.dumps(result, ensure_ascii=False)}")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone direct Presenton Create/Prepare/Generate/Export probe.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--log-file", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = Path(args.log_file).expanduser() if args.log_file else output_dir / f"presenton_direct_probe_{stamp}.log"

    probe = PresentonProbe(
        base_url=args.base_url,
        timeout=args.timeout,
        output_dir=output_dir,
        log_file=log_file,
        username=args.username,
        password=args.password,
    )
    result = probe.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
