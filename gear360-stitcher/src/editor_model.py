"""Persistent editing state for the 360 project editor."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import os


@dataclass(order=True)
class ReframeKeyframe:
    time_seconds: float
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    fov_deg: float = 90.0


@dataclass
class EditorProject:
    media_path: str = ""
    media_kind: str = ""
    trim_start: float = 0.0
    trim_end: float = 0.0
    keyframes: list[ReframeKeyframe] = field(default_factory=list)
    export_preset: str = "Reframed 1080p"

    def to_dict(self):
        data = asdict(self)
        data["keyframes"] = [asdict(keyframe) for keyframe in self.keyframes]
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(
            media_path=data.get("media_path", ""),
            media_kind=data.get("media_kind", ""),
            trim_start=float(data.get("trim_start", 0.0)),
            trim_end=float(data.get("trim_end", 0.0)),
            keyframes=[
                ReframeKeyframe(**keyframe) for keyframe in data.get("keyframes", [])
            ],
            export_preset=data.get("export_preset", "Reframed 1080p"),
        )

    def view_at(self, time_seconds):
        if not self.keyframes:
            return ReframeKeyframe(time_seconds)
        keyframes = sorted(self.keyframes)
        if time_seconds <= keyframes[0].time_seconds:
            return deepcopy(keyframes[0])
        if time_seconds >= keyframes[-1].time_seconds:
            return deepcopy(keyframes[-1])
        for before, after in zip(keyframes, keyframes[1:]):
            if before.time_seconds <= time_seconds <= after.time_seconds:
                ratio = (time_seconds - before.time_seconds) / (
                    after.time_seconds - before.time_seconds
                )
                return ReframeKeyframe(
                    time_seconds,
                    before.yaw_deg + (after.yaw_deg - before.yaw_deg) * ratio,
                    before.pitch_deg + (after.pitch_deg - before.pitch_deg) * ratio,
                    before.fov_deg + (after.fov_deg - before.fov_deg) * ratio,
                )
        return deepcopy(keyframes[-1])


class ProjectHistory:
    def __init__(self, project=None):
        self.project = project or EditorProject()
        self._undo = []
        self._redo = []

    def snapshot(self):
        self._undo.append(deepcopy(self.project))
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(deepcopy(self.project))
        self.project = self._undo.pop()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(deepcopy(self.project))
        self.project = self._redo.pop()
        return True

    def save(self, path):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(self.project.to_dict(), file, indent=2)

    def load(self, path):
        with open(path, "r", encoding="utf-8") as file:
            self.project = EditorProject.from_dict(json.load(file))
        self._undo.clear()
        self._redo.clear()
        if self.project.media_path and not os.path.isfile(self.project.media_path):
            raise FileNotFoundError(
                f"Project media file was not found:\n{self.project.media_path}"
            )
