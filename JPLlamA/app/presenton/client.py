from __future__ import annotations

import json
import os
import tempfile
import time
import zipfile

import logging
import threading

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Callable, Dict, List, Optional

import requests

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class PresentonConfig:
    base_url: str = "http://host.docker.internal:5001"
    username: str = ""
    password: str = ""
    template_name: Optional[str] = None
    default_template_name: str = "general"
    language: str = "English"
    timeout_seconds: int = 120
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0


class PresentonClient:
    _process_job_lock = threading.Lock()

    def __init__(self, config: PresentonConfig):
        self.config = config
        self._token: Optional[str] = None
        self._template_cache: Optional[Dict[str, Any]] = None
        self.session = requests.Session()

    def _acquire_global_job_lock(self) -> Optional[Any]:
        """
        Ensure only one Presenton presentation job runs at a time.
        Uses both an in-process mutex and an OS file lock for cross-process safety.
        """
        lock_path = os.environ.get(
            "JPLLAMA_PRESENTON_JOB_LOCKFILE",
            os.path.join(tempfile.gettempdir(), "jpllama_presenton_job.lock"),
        )
        logger.info("Presenton job lock: waiting for exclusive lock file=%s", lock_path)
        self._process_job_lock.acquire()
        lock_handle = None
        try:
            lock_handle = open(lock_path, "a+", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            logger.info("Presenton job lock: acquired file=%s", lock_path)
            return lock_handle
        except Exception:
            self._process_job_lock.release()
            if lock_handle is not None:
                try:
                    lock_handle.close()
                except Exception:
                    pass
            raise

    def _release_global_job_lock(self, lock_handle: Optional[Any]) -> None:
        try:
            if lock_handle is not None and fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                if lock_handle is not None:
                    lock_handle.close()
            finally:
                self._process_job_lock.release()
                logger.info("Presenton job lock: released")

    def _url(self, path: str) -> str:
        return self.config.base_url.rstrip("/") + path

    def _emit_status(
        self,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]],
        stage: str,
        **payload: Any,
    ) -> None:
        if on_status:
            on_status(stage, payload)

    def _ensure_not_cancelled(self, cancel_check: Optional[Callable[[], bool]]) -> None:
        if cancel_check and cancel_check():
            raise RuntimeError("Operation cancelled by user.")

    def _find_newest_pptx(self, directory: Path) -> Optional[Path]:
        if not directory.exists():
            return None

        candidates: List[Path] = []
        for candidate in directory.rglob("*.pptx"):
            if candidate.is_file() and not candidate.name.startswith("~$"):
                candidates.append(candidate)
        if not candidates:
            return None

        candidates.sort(key=lambda item: (item.stat().st_mtime, item.stat().st_size, str(item)))
        return candidates[-1]

    def _is_valid_pptx(self, candidate: Optional[Path]) -> bool:
        if candidate is None:
            return False
        if not candidate.exists() or not candidate.is_file():
            return False
        if candidate.suffix.lower() != ".pptx":
            return False
        if candidate.stat().st_size < 128:
            return False
        try:
            with zipfile.ZipFile(candidate, "r") as archive:
                names = set(archive.namelist())
        except Exception:
            return False

        has_types = "[Content_Types].xml" in names
        has_presentation = "ppt/presentation.xml" in names
        has_slide = any(name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names)
        return has_types and has_presentation and has_slide

    def _is_fresh_enough(self, candidate: Path, *, min_mtime: Optional[float]) -> bool:
        if min_mtime is None:
            return True
        try:
            return candidate.stat().st_mtime >= min_mtime
        except Exception:
            return False

    def _find_newest_valid_pptx(self, directory: Path, *, min_mtime: Optional[float] = None) -> Optional[Path]:
        if not directory.exists():
            return None

        candidates: List[Path] = []
        for candidate in directory.rglob("*.pptx"):
            if not candidate.is_file() or candidate.name.startswith("~$"):
                continue
            if not self._is_fresh_enough(candidate, min_mtime=min_mtime):
                continue
            if self._is_valid_pptx(candidate):
                candidates.append(candidate)

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.stat().st_mtime, item.stat().st_size, str(item)))
        return candidates[-1]

    def _copy_if_valid(self, source: Path, destination_dir: Path) -> Optional[Path]:
        if not self._is_valid_pptx(source):
            return None
        destination = destination_dir / source.name
        destination.write_bytes(source.read_bytes())
        if not self._is_valid_pptx(destination):
            return None
        return destination

    def _download_if_valid(self, url: str, destination: Path) -> Optional[Path]:
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=1800,
            stream=True,
        )
        response.raise_for_status()
        destination.write_bytes(response.content)
        if self._is_valid_pptx(destination):
            return destination
        try:
            destination.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        timeout: Optional[float] = None,
        retries_override: Optional[int] = None,
        request_label: Optional[str] = None,
    ) -> requests.Response:
        max_retries = self.config.max_retries if retries_override is None else max(0, retries_override)
        attempts = max(1, max_retries + 1)
        last_error: Optional[Exception] = None
        body_size = 0
        if json_body is not None:
            try:
                body_size = len(json.dumps(json_body, ensure_ascii=False).encode("utf-8"))
            except Exception:
                body_size = -1
        label = request_label or path
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                effective_timeout = (self.config.timeout_seconds if timeout is None else timeout)
                logger.info(
                    "Presenton request start: label=%s method=%s path=%s attempt=%s/%s timeout=%ss stream=%s body_bytes=%s",
                    label,
                    method.upper(),
                    path,
                    attempt,
                    attempts,
                    effective_timeout,
                    stream,
                    body_size,
                )
                response = self.session.request(
                    method.upper(),
                    self._url(path),
                    json=json_body,
                    params=params,
                    headers=self._headers(),
                    stream=stream,
                    timeout=effective_timeout,
                )
                response.raise_for_status()
                elapsed = round(time.monotonic() - started, 3)
                logger.info(
                    "Presenton request success: label=%s path=%s status_code=%s elapsed=%ss",
                    label,
                    path,
                    response.status_code,
                    elapsed,
                )
                return response
            except requests.RequestException as exc:
                last_error = exc
                elapsed = round(time.monotonic() - started, 3)
                logger.warning(
                    "Presenton request error: label=%s path=%s attempt=%s/%s elapsed=%ss error=%s",
                    label,
                    path,
                    attempt,
                    attempts,
                    elapsed,
                    exc,
                )
                if attempt >= attempts:
                    break
                time.sleep(self.config.retry_backoff_seconds * attempt)

        detail = str(last_error) if last_error else "unknown error"
        raise RuntimeError(f"Presenton request failed for {path}: {detail}") from last_error

    def _parse_json(self, response: requests.Response) -> Any:
        try:
            return response.json()
        except Exception:
            pass

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except ValueError:
                pass

        text = response.text.strip()
        if not text:
            return {}

        try:
            return json.loads(text)
        except ValueError:
            return text

    def _find_in_payload(self, payload: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys:
                    return value
                found = self._find_in_payload(value, keys)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._find_in_payload(item, keys)
                if found is not None:
                    return found
        return None

    def _login(self) -> Optional[str]:
        if self._token:
            return self._token

        if not self.config.username or not self.config.password:
            return None

        response = self.session.post(
            self._url("/api/v1/auth/login"),
            json={"username": self.config.username, "password": self.config.password},
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()

        payload = self._parse_json(response)
        token = self._find_in_payload(payload, ("access_token", "token", "accessToken"))
        if token:
            self._token = str(token)
        return self._token

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = self._login()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def create_presentation(
        self,
        content: str,
        title: str = "JPLlamA deck",
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        selected_template = self._select_template_name(template_name)
        payload = {
            "title": title,
            "content": content,
            "language": self.config.language,
        }
        if selected_template:
            payload["template"] = selected_template
            payload["template_name"] = selected_template
        response = self._request("POST", "/api/v1/ppt/presentation/create", json_body=payload)
        data = self._parse_json(response)
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"Unexpected create presentation response: {data}")

    def get_templates(self) -> List[Dict[str, Any]]:
        response = self._request("GET", "/api/v1/ppt/template/all")
        data = self._parse_json(response)

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            for key in ("templates", "items", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    return [value]

        return []

    def get_template(self, template_name: Optional[str] = None) -> Dict[str, Any]:
        wanted = (template_name or self.config.template_name).strip().lower()

        if self._template_cache and str(self._template_cache.get("name", "")).strip().lower() == wanted:
            return self._template_cache

        templates = self.get_templates()
        for template in templates:
            name = str(template.get("name", "")).strip().lower()
            if name == wanted:
                self._template_cache = template
                return template

        if templates:
            self._template_cache = templates[0]
            return templates[0]

        raise RuntimeError(f"No Presenton templates found for '{wanted}'")

    def prepare_presentation(
        self,
        presentation_id: str,
        outlines: List[Dict[str, str]],
        layout: Dict[str, Any],
        timeout: int = 120,
    ) -> Dict[str, Any]:
        logger.info(
            "Presenton prepare_presentation: sending prepare request for presentation %s with timeout=%ss",
            presentation_id,
            timeout,
        )
        # Presenton requires layout.slides in prepare payload; normalize minimal template payloads.
        raw_layout = self._normalise_layout(layout if isinstance(layout, dict) else {})
        # Avoid sending duplicated template payloads; keep prepare payload minimal and deterministic.
        layout_payload = {
            "name": raw_layout.get("name"),
            "slides": raw_layout.get("slides") or [],
            "theme": raw_layout.get("theme") or "default",
            "icon_weight": raw_layout.get("icon_weight") or "bold",
            "include_title_slide": raw_layout.get("include_title_slide", True),
            "include_table_of_contents": raw_layout.get("include_table_of_contents", False),
        }
        payload = {
            "presentation_id": presentation_id,
            "outlines": outlines,
            "layout": layout_payload,
        }
        try:
            payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        except Exception:
            payload_bytes = -1
        logger.info(
            "Presenton prepare debug: presentation_id=%s outlines=%s slides=%s payload_bytes=%s",
            presentation_id,
            len(outlines or []),
            len(layout_payload.get("slides") or []),
            payload_bytes,
        )
        try:
            response = self._request(
                "POST",
                "/api/v1/ppt/presentation/prepare",
                json_body=payload,
                timeout=timeout,
                retries_override=0,
                request_label="prepare",
            )
        except Exception as exc:
            logger.warning(
                "Presenton prepare failed: presentation_id=%s error=%s. Starting status probes.",
                presentation_id,
                exc,
            )
            for probe in range(1, 7):
                try:
                    probe_started = time.monotonic()
                    status_response = self.session.get(
                        self._url(f"/api/v1/ppt/presentation/status/{presentation_id}"),
                        headers=self._headers(),
                        timeout=5,
                    )
                    elapsed = round(time.monotonic() - probe_started, 3)
                    status_preview = (status_response.text or "")[:300].replace("\n", " ")
                    logger.info(
                        "Presenton prepare probe: presentation_id=%s probe=%s status_code=%s elapsed=%ss body=%s",
                        presentation_id,
                        probe,
                        status_response.status_code,
                        elapsed,
                        status_preview,
                    )
                except Exception as probe_exc:
                    logger.info(
                        "Presenton prepare probe error: presentation_id=%s probe=%s error=%s",
                        presentation_id,
                        probe,
                        probe_exc,
                    )
                time.sleep(5)
            raise
        data = self._parse_json(response)
        logger.info("Presenton prepare_presentation: prepare completed for presentation %s", presentation_id)
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"Unexpected prepare presentation response: {data}")

    def _normalise_layout(self, layout: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(layout, dict):
            layout = {}

        selected_template = self._select_template_name(layout.get("name"))
        slides = layout.get("slides")
        if not isinstance(slides, list) or not slides:
            slides = [
                {
                    "id": "slide-1",
                    "title": "Executive Summary",
                    "subtitle": "Summary",
                    "content": [],
                    "json_schema": {"type": "object", "properties": {}},
                }
            ]
        else:
            slides = [
                self._ensure_slide_schema(slide)
                for slide in slides
            ]

        normalised = {
            "slides": slides,
            "theme": layout.get("theme") or "default",
            "icon_weight": layout.get("icon_weight") or "bold",
            "include_title_slide": layout.get("include_title_slide", True),
            "include_table_of_contents": layout.get("include_table_of_contents", False),
        }
        if selected_template:
            normalised["name"] = selected_template

        for key, value in layout.items():
            if key not in normalised:
                normalised[key] = value
        return normalised

    def _ensure_slide_schema(self, slide: Any) -> Dict[str, Any]:
        if not isinstance(slide, dict):
            return {
                "id": "slide-1",
                "title": "Executive Summary",
                "subtitle": "Summary",
                "content": [],
                "json_schema": {"type": "object", "properties": {}},
            }
        return dict(slide)

    def stream_presentation(
        self,
        presentation_id: str,
        *,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_wait_seconds: Optional[float] = 45.0,
    ) -> str:
        response = self._request("GET", f"/api/v1/ppt/presentation/stream/{presentation_id}", stream=True)
        self._emit_status(on_status, "rendering", service="presenton", presentation_id=presentation_id)

        if not hasattr(response, "iter_lines"):
            return response.text

        try:
            lines = response.iter_lines(decode_unicode=True)
        except TypeError:
            lines = response.iter_lines()

        chunks: List[str] = []
        event_name: Optional[str] = None
        data_buffer: List[str] = []
        started_at = time.monotonic()

        for raw_line in lines:
            self._ensure_not_cancelled(cancel_check)
            if max_wait_seconds is not None and max_wait_seconds > 0:
                if (time.monotonic() - started_at) >= max_wait_seconds:
                    self._emit_status(
                        on_status,
                        "generating",
                        service="presenton",
                        presentation_id=presentation_id,
                        current_stage="stream-timeout",
                    )
                    break
            if raw_line is None:
                continue

            line = raw_line.strip()
            if not line:
                if event_name or data_buffer:
                    message = "\n".join(data_buffer).strip()
                    if message:
                        chunks.append(message)
                        self._emit_status(
                            on_status,
                            "generating",
                            service="presenton",
                            presentation_id=presentation_id,
                            message=message,
                        )
                    if event_name and event_name.lower() in {"completed", "complete", "done", "success", "error"}:
                        break
                    event_name = None
                    data_buffer = []
                continue

            if line.startswith(":"):
                continue

            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_buffer.append(line.split(":", 1)[1].strip())

        combined = "\n".join(chunks).strip()
        if combined:
            return combined
        return response.text

    def generate_presentation(
        self,
        content: str,
        *,
        n_slides: Optional[int] = None,
        language: Optional[str] = None,
        template: Optional[str] = None,
        instructions: Optional[str] = None,
        export_as: str = "pptx",
        output_dir: Optional[str] = None,
        presentation_id: Optional[str] = None,
        min_mtime: Optional[float] = None,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        self._emit_status(on_status, "connecting", service="presenton")
        started_at = time.time()
        selected_template = self._select_template_name(template)
        payload = {
            "content": content or "",
            "n_slides": n_slides,
            "language": language or self.config.language,
            "instructions": instructions,
            "export_as": export_as,
            "include_title_slide": True,
            "include_table_of_contents": False,
            "web_search": False,
            "tone": "default",
            "verbosity": "standard",
        }
        if selected_template:
            payload["template"] = selected_template
        if presentation_id:
            payload["presentation_id"] = presentation_id
        response = self._request("POST", "/api/v1/ppt/presentation/generate/async", json_body=payload)
        data = self._parse_json(response)
        self._emit_status(on_status, "accepted", service="presenton", payload=data if isinstance(data, dict) else {})
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected generate presentation response: {data}")

        task_id = data.get("id")
        if not task_id:
            raise RuntimeError(f"No generation task id returned: {data}")
        logger.info("Presenton generate_presentation: accepted task_id=%s", task_id)

        # Keep status polling bounded so export/generate cannot block indefinitely.
        status_timeout = float(max(5, min(int(self.config.timeout_seconds), 15)))
        max_wait_seconds = float(max(45, int(self.config.timeout_seconds)))
        poll_started_at = time.monotonic()

        resolved_path: Optional[Path] = None
        source_path: Optional[Path] = None
        destination: Optional[Path] = None

        poll_index = 0
        while True:
            poll_index += 1
            self._ensure_not_cancelled(cancel_check)
            total_elapsed = time.monotonic() - poll_started_at
            if total_elapsed >= max_wait_seconds:
                raise RuntimeError(
                    f"Presenton status polling timed out for task {task_id} after {round(total_elapsed, 2)}s"
                )
            try:
                status_response = self.session.get(
                    self._url(f"/api/v1/ppt/presentation/status/{task_id}"),
                    headers=self._headers(),
                    timeout=status_timeout,
                )
                status_response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning(
                    "Presenton status poll error: task_id=%s poll=%s elapsed=%ss error=%s",
                    task_id,
                    poll_index,
                    round(total_elapsed, 3),
                    exc,
                )
                time.sleep(2)
                continue
            status_payload = self._parse_json(status_response)
            if not isinstance(status_payload, dict):
                logger.info(
                    "Presenton status poll non-dict payload: task_id=%s poll=%s elapsed=%ss",
                    task_id,
                    poll_index,
                    round(total_elapsed, 3),
                )
                break

            status = str(status_payload.get("status") or "").lower()
            payload_data = status_payload.get("data") if isinstance(status_payload.get("data"), dict) else {}
            logger.info(
                "Presenton status poll: task_id=%s poll=%s elapsed=%ss status=%s stage=%s",
                task_id,
                poll_index,
                round(total_elapsed, 3),
                status,
                payload_data.get("stage") or payload_data.get("step") or "",
            )
            self._emit_status(
                on_status,
                "generating",
                service="presenton",
                task_id=task_id,
                status=status,
                current_slide=payload_data.get("current_slide") or payload_data.get("slide") or payload_data.get("slide_index"),
                current_stage=payload_data.get("stage") or payload_data.get("step"),
            )

            # Some Presenton backends keep task status pending even when the presentation status is terminal.
            if status in {"pending", "running", "queued", "processing"} and presentation_id and (poll_index % 5 == 0):
                try:
                    presentation_status_response = self.session.get(
                        self._url(f"/api/v1/ppt/presentation/status/{presentation_id}"),
                        headers=self._headers(),
                        timeout=status_timeout,
                    )
                    presentation_status_response.raise_for_status()
                    presentation_status_payload = self._parse_json(presentation_status_response)
                    if isinstance(presentation_status_payload, dict):
                        presentation_status = str(presentation_status_payload.get("status") or "").lower()
                        presentation_data = (
                            presentation_status_payload.get("data")
                            if isinstance(presentation_status_payload.get("data"), dict)
                            else {}
                        )
                        logger.info(
                            "Presenton presentation-status probe: presentation_id=%s poll=%s elapsed=%ss status=%s stage=%s",
                            presentation_id,
                            poll_index,
                            round(total_elapsed, 3),
                            presentation_status,
                            presentation_data.get("stage") or presentation_data.get("step") or "",
                        )
                        if presentation_status in {"completed", "succeeded", "success"}:
                            logger.info(
                                "Presenton generate fallback: using presentation status terminal state for presentation_id=%s task_id=%s",
                                presentation_id,
                                task_id,
                            )
                            status_payload = presentation_status_payload
                            status = presentation_status
                            payload_data = presentation_data
                except requests.RequestException as exc:
                    logger.warning(
                        "Presenton presentation-status probe error: presentation_id=%s poll=%s elapsed=%ss error=%s",
                        presentation_id,
                        poll_index,
                        round(total_elapsed, 3),
                        exc,
                    )

            if status in {"completed", "succeeded", "success"}:
                payload_data = status_payload.get("data") or {}
                path = payload_data.get("path") if isinstance(payload_data, dict) else None
                presentation_id = payload_data.get("presentation_id") or payload_data.get("id") or data.get("presentation_id")
                if output_dir and path:
                    destination = Path(output_dir).expanduser()
                    destination.mkdir(parents=True, exist_ok=True)
                    source_path = Path(str(path)).expanduser()
                    copied_path = None
                    if source_path.exists() and self._is_fresh_enough(source_path, min_mtime=min_mtime):
                        copied_path = self._copy_if_valid(source_path, destination)
                    if copied_path is not None:
                        resolved_path = copied_path
                        self._emit_status(on_status, "exporting", service="presenton", path=str(copied_path))
                        return {
                            "presentation_id": presentation_id,
                            "path": str(copied_path),
                            "filename": copied_path.name,
                            "folder": str(copied_path.parent),
                            "source_path": str(source_path),
                            "output_dir": str(destination),
                            "exists": True,
                            "payload": status_payload,
                        }
                    try:
                        url = self._url(path) if not str(path).startswith("http") else str(path)
                        copied_path = destination / (source_path.name or f"{presentation_id or task_id}.pptx")
                        downloaded_path = self._download_if_valid(url, copied_path)
                        if downloaded_path is not None:
                            resolved_path = downloaded_path
                            self._emit_status(on_status, "exporting", service="presenton", path=str(downloaded_path))
                            return {
                                "presentation_id": presentation_id,
                                "path": str(downloaded_path),
                                "filename": downloaded_path.name,
                                "folder": str(downloaded_path.parent),
                                "source_path": str(source_path),
                                "output_dir": str(destination),
                                "exists": True,
                                "payload": status_payload,
                            }
                    except Exception:
                        pass

                if output_dir:
                    destination = Path(output_dir).expanduser()
                    destination.mkdir(parents=True, exist_ok=True)
                    recovered = self._find_newest_valid_pptx(destination, min_mtime=min_mtime)
                    if recovered is not None:
                        resolved_path = recovered
                        return {
                            "presentation_id": presentation_id,
                            "path": str(recovered),
                            "filename": recovered.name,
                            "folder": str(recovered.parent),
                            "source_path": str(source_path or path or ""),
                            "output_dir": str(destination),
                            "exists": True,
                            "recovered": True,
                            "payload": status_payload,
                        }

                if path:
                    candidate_path = Path(str(path)).expanduser()
                    if self._is_valid_pptx(candidate_path) and self._is_fresh_enough(candidate_path, min_mtime=min_mtime):
                        resolved_path = candidate_path
                    else:
                        resolved_path = None
                elif destination is not None:
                    resolved_path = self._find_newest_valid_pptx(destination, min_mtime=min_mtime)

                return {
                    "presentation_id": presentation_id,
                    "path": str(resolved_path) if resolved_path is not None else "",
                    "filename": resolved_path.name if resolved_path is not None else "",
                    "folder": str(resolved_path.parent) if resolved_path is not None else (str(destination) if destination else ""),
                    "source_path": str(source_path or path or ""),
                    "output_dir": str(destination) if destination is not None else (str(output_dir) if output_dir else ""),
                    "exists": bool(resolved_path and resolved_path.exists()),
                    "valid_pptx": bool(resolved_path and self._is_valid_pptx(resolved_path)),
                    "payload": status_payload,
                }

            if status in {"failed", "error"}:
                raise RuntimeError(f"Presenton generation failed: {status_payload}")

            time.sleep(2)

        raise RuntimeError(
            f"Presenton generation did not reach a terminal success state for task {task_id} within {int(max_wait_seconds)}s"
        )

    def export_presentation(
        self,
        presentation_id: str,
        output_path: Optional[str] = None,
        download_format: str = "pptx",
        min_mtime: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self.generate_presentation(
            content="Presentation export",
            n_slides=1,
            language=self.config.language,
            template=self._select_template_name(None),
            instructions=None,
            export_as=download_format,
            output_dir=output_path,
            presentation_id=presentation_id,
            min_mtime=min_mtime,
        )

    def _select_template_name(self, requested: Optional[str]) -> Optional[str]:
        candidate = (requested if requested is not None else self.config.template_name)
        if candidate is None:
            candidate = self.config.default_template_name
        value = str(candidate).strip()
        return value or None

    def download_presentation(
        self,
        presentation_id: str,
        output_path: Optional[str] = None,
        min_mtime: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self.export_presentation(presentation_id, output_path=output_path, min_mtime=min_mtime)

    def build_presentation(
        self,
        content: str,
        outlines: list[dict],
        *,
        template_name: Optional[str] = None,
        output_dir: Optional[str] = None,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict:
        lock_handle = self._acquire_global_job_lock()
        try:
            run_started_at = time.time()
            fresh_threshold = run_started_at - 1
            selected_template = self._select_template_name(template_name)
            self._emit_status(on_status, "connecting", service="presenton")
            logger.info("Presenton build_presentation: calling create_presentation")
            created = self.create_presentation(content, template_name=selected_template)
            self._emit_status(on_status, "accepted", service="presenton", payload=created)
            logger.info("Presenton build_presentation: create_presentation completed")

            presentation_id = created.get("id") or created.get("presentation_id")
            if not presentation_id:
                raise RuntimeError(f"No presentation id returned: {created}")

            logger.info("Presenton build_presentation: preparing layout payload")
            template = self._normalise_layout({"name": selected_template} if selected_template else {})
            self._emit_status(on_status, "generating", service="presenton", current_stage="template")
            logger.info("Presenton build_presentation: layout payload prepared")

            logger.info("Presenton build_presentation: calling prepare_presentation")
            prepared = self.prepare_presentation(
                presentation_id=presentation_id,
                outlines=outlines,
                layout=template,
                timeout=int(max(30, self.config.timeout_seconds)),
            )
            self._emit_status(on_status, "generating", service="presenton", current_stage="prepare")
            logger.info("Presenton build_presentation: prepare_presentation completed")

            logger.info("Presenton build_presentation: calling generate_presentation")
            rendered = self.generate_presentation(
                content=content or "Executive summary",
                n_slides=max(1, len(outlines or [])),
                language=self.config.language,
                template=selected_template,
                instructions=None,
                export_as="pptx",
                output_dir=output_dir,
                presentation_id=presentation_id,
                min_mtime=fresh_threshold,
                on_status=on_status,
                cancel_check=cancel_check,
            )
            logger.info("Presenton build_presentation: generate_presentation completed")

            logger.info("Presenton build_presentation: calling stream_presentation")
            try:
                streamed = self.stream_presentation(
                    presentation_id,
                    on_status=on_status,
                    cancel_check=cancel_check,
                    max_wait_seconds=float(max(15, self.config.timeout_seconds)),
                )
                logger.info("Presenton build_presentation: stream_presentation completed")
            except Exception as exc:
                logger.warning("Presenton build_presentation: stream_presentation skipped due to error: %s", exc)
                streamed = {"warning": str(exc)}
                self._emit_status(on_status, "generating", service="presenton", current_stage="stream-timeout")

            logger.info("Presenton build_presentation: calling export_presentation")
            self._emit_status(on_status, "exporting", service="presenton")
            try:
                exported = self.export_presentation(
                    presentation_id,
                    output_path=output_dir,
                    min_mtime=fresh_threshold,
                )
            except Exception as exc:
                logger.warning("Presenton build_presentation: export_presentation fallback using rendered path due to error: %s", exc)
                rendered_path = rendered.get("path") if isinstance(rendered, dict) else None
                exported = {
                    "presentation_id": presentation_id,
                    "path": rendered_path,
                    "warning": str(exc),
                }
            self._emit_status(on_status, "finished", service="presenton", path=exported.get("path"))
            logger.info("Presenton build_presentation: export_presentation completed")

            export_path = Path(str(exported.get("path"))).expanduser() if isinstance(exported, dict) and exported.get("path") else None
            rendered_path = Path(str(rendered.get("path"))).expanduser() if isinstance(rendered, dict) and rendered.get("path") else None

            final_candidate: Optional[Path] = None
            if self._is_valid_pptx(export_path):
                if self._is_fresh_enough(export_path, min_mtime=fresh_threshold):
                    final_candidate = export_path
            elif self._is_valid_pptx(rendered_path):
                if self._is_fresh_enough(rendered_path, min_mtime=fresh_threshold):
                    final_candidate = rendered_path
            elif output_dir:
                recovered = self._find_newest_valid_pptx(Path(output_dir).expanduser(), min_mtime=fresh_threshold)
                if recovered is not None:
                    final_candidate = recovered

            final_path = str(final_candidate) if final_candidate is not None else ""
            if not final_path:
                raise RuntimeError("Presenton completed but no new valid PPTX was produced for this run.")

            return {
                "presentation_id": presentation_id,
                "path": final_path,
                "filename": final_candidate.name if final_candidate is not None else "",
                "folder": str(final_candidate.parent) if final_candidate is not None else "",
                "template": selected_template,
                "started_at": run_started_at,
                "created": created,
                "prepared": prepared,
                "rendered": rendered,
                "stream": streamed,
                "export": exported,
            }
        finally:
            self._release_global_job_lock(lock_handle)
