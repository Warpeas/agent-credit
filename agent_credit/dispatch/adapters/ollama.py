from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..base import Preflight, Provider, Result, Task


class OllamaProvider(Provider):
    """本地 Ollama。不消耗任何云端额度，因此永远不因余额被跳过。"""

    name = "ollama"
    capabilities = {"text", "commit", "explain", "code-gen", "test-gen"}
    supports_balance = False
    unbounded = True

    @property
    def base_url(self) -> str:
        return str(self.config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")

    @property
    def model(self) -> str:
        return str(self.config.get("model") or "qwen3:8b-q4_K_M")

    def _request(self, path: str, payload: dict | None, timeout: float) -> dict:
        url = f"{self.base_url}{path}"
        if payload is None:
            req = urllib.request.Request(url, method="GET")
        else:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def preflight(self, task: Task) -> Preflight:
        try:
            data = self._request("/api/tags", None, timeout=10)
        except (urllib.error.URLError, OSError) as exc:
            return Preflight(available=False, reason=f"Ollama 服务不可达: {exc}")
        models = {m.get("name") for m in data.get("models") or []}
        if self.model not in models:
            return Preflight(
                available=False,
                reason=f"本地未安装模型 {self.model}（ollama pull {self.model}）",
            )
        return Preflight(available=True, balance_note="本地推理，不消耗额度")

    def read_balance(self) -> tuple[int | None, str]:
        return None, "本地模型不消耗额度"

    def dispatch(self, task: Task) -> Result:
        payload = {
            "model": self.model,
            "prompt": task.text,
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": int(self.config.get("num_ctx") or 8192),
                "num_predict": int(self.config.get("num_predict") or 600),
                "temperature": float(self.config.get("temperature") or 0.2),
            },
        }
        # 派单主题：Ollama 没有服务端持久化，只有 /api/generate 的 system 字段，
        # 每次请求带上（多行没问题，不走 .cmd shim）。
        theme = self.theme_text()
        if theme:
            payload["system"] = theme
        started = time.time()
        try:
            data = self._request("/api/generate", payload, timeout=task.timeout_s)
        except urllib.error.HTTPError as exc:
            # 非 thinking 模型不接受 think 参数，去掉后重试一次
            payload.pop("think", None)
            try:
                data = self._request("/api/generate", payload, timeout=task.timeout_s)
            except urllib.error.HTTPError as exc2:
                return Result(ok=False, exit_code=exc2.code, note=f"HTTP {exc2.code}: {exc2.reason}",
                              duration_s=time.time() - started)
        except (urllib.error.URLError, OSError) as exc:
            return Result(ok=False, exit_code=69, note=f"请求失败: {exc}", duration_s=time.time() - started)

        duration = time.time() - started
        text = (data.get("response") or "").strip()
        eval_count = int(data.get("eval_count") or 0)
        eval_dur = (data.get("eval_duration") or 0) / 1e9
        speed = f"{eval_count / eval_dur:.1f} tok/s" if eval_dur else "n/a"
        return Result(
            ok=bool(text),
            # 本地模型没有额度可限，空输出只是"跑完但没正文"（契约里的 1），
            # 不能借用 3（疑似额度/限流），否则 --history 的限流统计会失真。
            exit_code=0 if text else 1,
            text=text,
            duration_s=duration,
            note=f"{self.model}, {speed}, {eval_count} tok" if text else "模型无输出",
        )
