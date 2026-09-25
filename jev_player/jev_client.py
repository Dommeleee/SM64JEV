"""Minimal client for TypeSafe's Jev decision model (standard library only).

API: POST https://api.typesafe.ai/v1/systemone
     body {"state": ..., "model": "jev-latest", "questions": {...}}
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # USD; output is free
KEY_FILE = Path.home() / ".jev-mario" / "api_key"


class JevError(Exception):
    pass


class BudgetExceeded(JevError):
    pass


def load_api_key() -> str | None:
    """API key from the environment or ~/.jev-mario/api_key (never from the repository)."""
    for name in ("JEV_API_KEY", "TYPESAFE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def save_api_key(key: str) -> Path:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip() + "\n")
    KEY_FILE.chmod(0o600)
    return KEY_FILE


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0

    @property
    def cost(self) -> float:
        return self.input_tokens * PRICE_PER_INPUT_TOKEN


class JevClient:
    def __init__(self, api_key: str, budget_usd: float, model: str = DEFAULT_MODEL, timeout: float = 5.0):
        self.api_key = api_key
        self.budget_usd = budget_usd
        self.model = model
        self.timeout = timeout
        self.usage = Usage()

    def ask(self, state: dict, questions: dict) -> dict:
        """Send one request and return the `answers` dict."""
        if self.usage.cost >= self.budget_usd:
            raise BudgetExceeded(f"Budget von {self.budget_usd:.2f} $ aufgebraucht")
        body = json.dumps({"state": state, "model": self.model, "questions": questions}).encode()
        request = urllib.request.Request(
            API_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "jev-mario/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise JevError(f"HTTP {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise JevError(f"Verbindung fehlgeschlagen: {error}") from None
        except json.JSONDecodeError:
            raise JevError("Antwort war kein JSON") from None

        self.usage.calls += 1
        self.usage.input_tokens += int(payload.get("usage", {}).get("input_tokens") or 0)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise JevError(f"Unerwartete Antwort: {str(payload)[:300]}")
        return answers
