from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..revenue.events import parse_iso_datetime, utc_now

# Goal IDs must be UUIDs we generated; this guard rejects any path-traversal or
# weird characters reaching disk operations from untrusted WebSocket clients.
_GOAL_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _validate_goal_id(goal_id: str) -> str:
    if not isinstance(goal_id, str):
        raise ValueError("goal_id must be a string")
    text = goal_id.strip().lower()
    if not _GOAL_ID_RE.match(text):
        raise ValueError("goal_id is not a valid UUID")
    return text


@dataclass
class Goal:
    id: str
    name: str
    target_points: int
    started_at: datetime
    manual_adjustment: float = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "target_points": self.target_points,
            "started_at": self.started_at.isoformat(),
            "manual_adjustment": self.manual_adjustment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Goal:
        return cls(
            id=str(data["id"]), name=str(data["name"]), target_points=int(data["target_points"]),
            started_at=parse_iso_datetime(data.get("started_at")),
            manual_adjustment=float(data.get("manual_adjustment", 0)),
        )


class GoalStore:
    def __init__(self, goals_directory: Path):
        self.goals_directory = goals_directory
        self._active_path = goals_directory / "active_goal.json"
        self._lock = threading.RLock()

    def ensure_initialized(self) -> None:
        self.goals_directory.mkdir(parents=True, exist_ok=True)

    def list_goals(self) -> list[Goal]:
        with self._lock:
            self.ensure_initialized()
            goals = []
            for path in sorted(self.goals_directory.glob("*.json")):
                if path.name == "active_goal.json":
                    continue
                if not _GOAL_ID_RE.match(path.stem.lower()):
                    continue
                goals.append(self._read_goal_file(path))
            return sorted(goals, key=lambda goal: goal.started_at, reverse=True)

    def get_goal(self, goal_id: str) -> Goal | None:
        try:
            valid_id = _validate_goal_id(goal_id)
        except ValueError:
            return None
        with self._lock:
            path = self._goal_path(valid_id)
            if not path.is_file():
                return None
            return self._read_goal_file(path)

    def create_goal(self, name: str, target_points: int, started_at: datetime | None = None) -> Goal:
        if target_points <= 0:
            raise ValueError("target_points must be positive")
        if not name.strip():
            raise ValueError("name is required")
        with self._lock:
            self.ensure_initialized()
            goal = Goal(id=str(uuid.uuid4()), name=name.strip(), target_points=target_points, started_at=started_at or utc_now())
            self._write_goal(goal)
            return goal

    def save_goal(self, goal: Goal) -> Goal:
        _validate_goal_id(goal.id)
        with self._lock:
            self._write_goal(goal)
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        valid_id = _validate_goal_id(goal_id)
        with self._lock:
            path = self._goal_path(valid_id)
            if not path.is_file():
                return False
            path.unlink()
            if self.get_active_goal_id() == valid_id:
                self.clear_active_goal()
            return True

    def get_active_goal_id(self) -> str | None:
        with self._lock:
            self.ensure_initialized()
            if not self._active_path.is_file():
                return None
            data = json.loads(self._active_path.read_text(encoding="utf-8"))
            value = data.get("active_goal_id")
            if not value:
                return None
            try:
                return _validate_goal_id(str(value))
            except ValueError:
                return None

    def set_active_goal_id(self, goal_id: str) -> None:
        valid_id = _validate_goal_id(goal_id)
        with self._lock:
            if self.get_goal(valid_id) is None:
                raise ValueError(f"unknown goal id: {valid_id}")
            self.ensure_initialized()
            self._active_path.write_text(
                json.dumps({"active_goal_id": valid_id}, indent=2), encoding="utf-8",
            )

    def clear_active_goal(self) -> None:
        with self._lock:
            if self._active_path.is_file():
                self._active_path.unlink()

    def get_active_goal(self) -> Goal | None:
        active_id = self.get_active_goal_id()
        return self.get_goal(active_id) if active_id else None

    def _goal_path(self, goal_id: str) -> Path:
        # goal_id is pre-validated by callers; never accept untrusted input here.
        return self.goals_directory / f"{goal_id}.json"

    def _read_goal_file(self, path: Path) -> Goal:
        return Goal.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _write_goal(self, goal: Goal) -> None:
        self.ensure_initialized()
        self._goal_path(goal.id).write_text(json.dumps(goal.to_dict(), indent=2), encoding="utf-8")
