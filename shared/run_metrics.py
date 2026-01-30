import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_template(template: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (template or "").replace("{timestamp}", timestamp)


@dataclass
class RunMetrics:
    """
    Lightweight run metrics tracker.

    Intended for long-running headless scrapes where partial success is acceptable.
    """

    board: str
    started_at_iso: str = field(default_factory=_utc_now_iso)
    started_at_monotonic: float = field(default_factory=time.monotonic)
    counters: Dict[str, int] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    output_path: Optional[Path] = None

    def inc(self, key: str, amount: int = 1) -> None:
        if not key:
            return
        self.counters[key] = int(self.counters.get(key, 0)) + int(amount)

    def record_event(self, kind: str, **data: Any) -> None:
        if not kind:
            return
        payload: dict[str, Any] = {"t": _utc_now_iso(), "kind": kind}
        payload.update({k: v for k, v in data.items() if v is not None})
        self.events.append(payload)

    def set_output_path(self, path: Path) -> None:
        self.output_path = path

    def to_dict(self, *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ended_at_iso = _utc_now_iso()
        duration_seconds = max(time.monotonic() - self.started_at_monotonic, 0.0)
        payload: Dict[str, Any] = {
            "board": self.board,
            "started_at": self.started_at_iso,
            "ended_at": ended_at_iso,
            "duration_seconds": round(duration_seconds, 3),
            "counters": dict(self.counters),
        }
        if self.events:
            payload["events"] = list(self.events)
        if extra:
            payload["extra"] = dict(extra)
        if self.output_path is not None:
            payload["output_path"] = str(self.output_path)
        return payload

    def write_json(self, *, template: str, extra: Optional[Dict[str, Any]] = None) -> Path:
        rendered = _render_template(template) or "output/run_metrics_{timestamp}.json"
        path = Path(rendered)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict(extra=extra)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self.output_path = path
        return path

