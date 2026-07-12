from __future__ import annotations

from dataclasses import dataclass
import json
import time

from typing import Any, Callable, Dict, List, Optional

import requests

@dataclass

class OllamaConfig:

    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 1800
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0

class OllamaClient:

    def __init__(self, config: OllamaConfig):

        self.config = config

    def _url(self, path: str) -> str:

        return self.config.base_url.rstrip("/") + path

    def _request_with_retry(self, method: str, path: str, **kwargs) -> requests.Response:
        last_error: Optional[Exception] = None
        attempts = max(1, self.config.max_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                response = requests.request(
                    method,
                    self._url(path),
                    timeout=self.config.timeout_seconds,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                sleep_seconds = self.config.retry_backoff_seconds * attempt
                time.sleep(sleep_seconds)

        raise RuntimeError(
            f"Unable to reach Ollama at {self.config.base_url}. Ensure Ollama is running and network access is allowed."
        ) from last_error

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        on_status: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        if on_status:
            on_status("connecting", {"service": "ollama", "model": model})

        response = self._request_with_retry(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": stream,
            },
            stream=stream,
        )

        if on_status:
            on_status("loading_model", {"service": "ollama", "model": model})

        if not stream:
            data: Dict[str, Any] = response.json()
            content = data["message"]["content"]
            if on_status:
                on_status("completed", {"service": "ollama", "model": model, "chars": len(content)})
            return content

        chunks: List[str] = []
        token_count = 0
        if on_status:
            on_status("generating_response", {"service": "ollama", "model": model})

        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_check and cancel_check():
                    raise RuntimeError("Operation cancelled by user.")
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except Exception:
                    continue

                message_payload = payload.get("message") if isinstance(payload, dict) else None
                delta = ""
                if isinstance(message_payload, dict):
                    delta = str(message_payload.get("content") or "")
                if delta:
                    chunks.append(delta)
                    token_count += 1
                    if on_status:
                        on_status(
                            "streaming_tokens",
                            {
                                "service": "ollama",
                                "model": model,
                                "token_count": token_count,
                                "delta": delta,
                            },
                        )

                if bool(payload.get("done")):
                    break
        finally:
            try:
                response.close()
            except Exception:
                pass

        content = "".join(chunks)
        if on_status:
            on_status("completed", {"service": "ollama", "model": model, "tokens": token_count, "chars": len(content)})
        return content

    def list_models(self) -> List[str]:
        response = self._request_with_retry("GET", "/api/tags")

        return [m["name"] for m in response.json()["models"]]