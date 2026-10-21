"""Read LeRobot v3 datasets and turn their columns into TaskWitness episodes.

LeRobot (https://github.com/huggingface/lerobot) v3 stores frames in shared parquet
shards, with a `timestamp` and `episode_index` per frame, per-episode offsets in
`meta/episodes/`, task text in `meta/tasks.parquet` and one MP4 per camera that
concatenates several episodes. This module reads that layout directly with
pyarrow (`pip install taskwitness[lerobot]`); it does not need the `lerobot` package
or a GPU, and never touches the videos.

It was written against the real format and checked on REASSEMBLE's LeRobot port
(149 episodes, 1.4 M frames); see docs/REAL_DATA.en.md.

A mapping says which dataset columns become which TaskWitness sensor streams:

    {
      "task": {"type": "grasp", "object": {"name": "peg", "width_m_min": 0.004, "width_m_max": 0.008}},
      "sensors": {"gripper_width": {"column": "observation.state.gripper_position", "index": 0, "field": "width_m"}},
      "segments": {"column": "segment.index"},
      "label": {"column": "segment.success", "reduce": "last"},
      "task_prefix": "Pick "
    }

Sensor entries by stream: `load_cell` (field `grams`), `gripper_width` (`width_m`),
`button` (`pressed`, with `threshold`) and `gripper` (`state`, with `open_above`).
`scale` and `index` apply to any of them. `segments` turns each contiguous run of
a column into its own episode (REASSEMBLE stores a long recording of many actions
as one LeRobot episode). `label` reads the human label, `reduce` being `last`,
`any` or `all`. `task_prefix` keeps only frames whose task text starts with it.

Limits: one LeRobot episode must lie within one data file (always true in files
written by LeRobot's own tools), and timestamps are taken from the `timestamp` column.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskwitness.core import EPISODE_SCHEMA, TaskWitnessError

SUPPORTED_VERSIONS = ("v3.0", "v3.1")
STREAM_FIELDS = {"load_cell": "grams", "gripper_width": "width_m", "button": "pressed", "gripper": "state"}


class LeRobotError(TaskWitnessError):
    """Raised for unreadable datasets and invalid mappings."""


def _pq():
    try:
        import pyarrow.parquet as pq
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise LeRobotError("reading LeRobot datasets needs pyarrow: pip install 'taskwitness[lerobot]'") from None
    return pq


def _scalar(value: Any) -> Any:
    return value[0] if isinstance(value, (list, tuple)) else value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class EpisodeInfo:
    index: int
    length: int
    data_file: Path
    tasks: tuple[str, ...]
    meta: dict[str, Any]


class LeRobotDataset:
    """A local LeRobot v3 dataset directory (for example one downloaded from the Hugging Face Hub)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        info_path = self.root / "meta" / "info.json"
        if not info_path.exists():
            raise LeRobotError(f"{self.root} is not a LeRobot dataset: meta/info.json is missing")
        self.info = json.loads(info_path.read_text(encoding="utf-8"))
        version = self.info.get("codebase_version")
        if version not in SUPPORTED_VERSIONS:
            raise LeRobotError(f"unsupported LeRobot dataset version {version!r}; this reader handles {SUPPORTED_VERSIONS}")
        self.fps = float(self.info.get("fps", 0)) or None
        self.features: dict[str, Any] = self.info.get("features", {})
        pq = _pq()
        tasks_path = self.root / "meta" / "tasks.parquet"
        self.tasks: dict[int, str] = {}
        if tasks_path.exists():
            rows = pq.read_table(tasks_path).to_pylist()
            self.tasks = {int(r["task_index"]): str(r["task"]) for r in rows}
        self._episodes = self._read_episodes(pq)
        self._digests: dict[Path, str] = {}

    def _read_episodes(self, pq) -> list[EpisodeInfo]:
        files = sorted((self.root / "meta" / "episodes").rglob("*.parquet"))
        if not files:
            raise LeRobotError(f"{self.root}: meta/episodes has no parquet files")
        template = self.info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
        episodes = []
        for path in files:
            for row in pq.read_table(path).to_pylist():
                data = self.root / template.format(chunk_index=row["data/chunk_index"], file_index=row["data/file_index"])
                episodes.append(EpisodeInfo(int(row["episode_index"]), int(row["length"]), data, tuple(row.get("tasks") or ()), row))
        return sorted(episodes, key=lambda e: e.index)

    @property
    def episodes(self) -> list[EpisodeInfo]:
        return list(self._episodes)

    def digest(self, path: Path) -> str:
        if path not in self._digests:
            self._digests[path] = file_sha256(path)
        return self._digests[path]

    def check_columns(self, columns: list[str]) -> None:
        missing = [c for c in columns if c not in self.features and c not in ("timestamp", "episode_index", "task_index", "frame_index", "index")]
        if missing:
            raise LeRobotError(f"column(s) {missing} not in this dataset; available: {sorted(k for k in self.features if self.features[k].get('dtype') != 'video')}")

    def frames(self, columns: list[str], episodes: set[int] | None = None) -> Iterator[tuple[EpisodeInfo, dict[str, list]]]:
        """Yield (episode, {column: per-frame values}) for each wanted episode, one data file at a time."""
        self.check_columns(columns)
        pq = _pq()
        wanted = {c: None for c in ["episode_index", "timestamp", "task_index", *columns]}
        by_file: dict[Path, list[EpisodeInfo]] = {}
        for ep in self._episodes:
            if episodes is None or ep.index in episodes:
                by_file.setdefault(ep.data_file, []).append(ep)
        for path, infos in sorted(by_file.items()):
            if not path.exists():
                raise LeRobotError(f"data file {path} is missing; download the dataset's data/ folder")
            table = pq.read_table(path, columns=list(wanted))
            data = {c: table.column(c).to_pylist() for c in wanted}
            episode_of = [_scalar(v) for v in data["episode_index"]]
            for info in infos:
                rows = [i for i, e in enumerate(episode_of) if e == info.index]
                if not rows:
                    raise LeRobotError(f"episode {info.index} has no frames in {path.name}")
                if rows[-1] - rows[0] + 1 != len(rows):
                    raise LeRobotError(f"episode {info.index} is not contiguous in {path.name}")
                yield info, {c: v[rows[0] : rows[-1] + 1] for c, v in data.items()}

    def video_span(self, episode: int, camera: str) -> tuple[Path, float, float]:
        """(mp4 file, start s, end s) of an episode's camera stream inside its concatenated video file."""
        ep = next((e for e in self._episodes if e.index == episode), None)
        key = f"observation.images.{camera}" if not camera.startswith("observation.") else camera
        if ep is None or f"videos/{key}/from_timestamp" not in ep.meta:
            raise LeRobotError(f"no video span for episode {episode}, camera {camera!r}")
        template = self.info.get("video_path", "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4")
        path = self.root / template.format(video_key=key, chunk_index=ep.meta[f"videos/{key}/chunk_index"], file_index=ep.meta[f"videos/{key}/file_index"])
        return path, float(ep.meta[f"videos/{key}/from_timestamp"]), float(ep.meta[f"videos/{key}/to_timestamp"])


# ----------------------------------------------------------------------------- mapping


def validate_mapping(mapping: Any, dataset: LeRobotDataset | None = None) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise LeRobotError("mapping must be a JSON object")
    unknown = set(mapping) - {"task", "sensors", "segments", "label", "task_prefix"}
    if unknown:
        raise LeRobotError(f"unknown mapping key(s) {sorted(unknown)}")
    task = mapping.get("task")
    if not isinstance(task, dict) or "type" not in task:
        raise LeRobotError("mapping.task must be an object with a 'type'")
    sensors = mapping.get("sensors")
    if not isinstance(sensors, dict) or not sensors:
        raise LeRobotError("mapping.sensors must list at least one stream")
    for stream, spec in sensors.items():
        if stream not in STREAM_FIELDS:
            raise LeRobotError(f"unknown sensor stream {stream!r}; known: {sorted(STREAM_FIELDS)}")
        if not isinstance(spec, dict) or "column" not in spec:
            raise LeRobotError(f"mapping.sensors.{stream} needs a 'column'")
        if "field" in spec and spec["field"] != STREAM_FIELDS[stream]:
            raise LeRobotError(f"mapping.sensors.{stream}.field must be {STREAM_FIELDS[stream]!r}")
        if stream == "button" and "threshold" not in spec:
            raise LeRobotError("mapping.sensors.button needs a 'threshold' (value above which the button is pressed)")
        if stream == "gripper" and "open_above" not in spec:
            raise LeRobotError("mapping.sensors.gripper needs 'open_above' (value above which the gripper is open)")
    label = mapping.get("label")
    if label is not None and (not isinstance(label, dict) or "column" not in label or label.get("reduce", "last") not in ("last", "any", "all")):
        raise LeRobotError("mapping.label needs a 'column' and a 'reduce' of last, any or all")
    columns = [s["column"] for s in sensors.values()] + [c["column"] for c in (mapping.get("segments"), label) if c]
    if dataset is not None:
        dataset.check_columns(columns)
    return mapping


def _convert(stream: str, spec: dict[str, Any], values: list) -> list:
    out = []
    for v in values:
        x = v[spec.get("index", 0)] if isinstance(v, (list, tuple)) else v
        x = float(x) * float(spec.get("scale", 1.0))
        if stream == "button":
            out.append(x > float(spec["threshold"]))
        elif stream == "gripper":
            out.append("open" if x > float(spec["open_above"]) else "closed")
        else:
            out.append(x)
    return out


def _runs(values: list) -> list[tuple[Any, int, int]]:
    """Contiguous runs of equal values: (value, start, stop)."""
    runs, start = [], 0
    for i in range(1, len(values) + 1):
        if i == len(values) or values[i] != values[start]:
            runs.append((values[start], start, i))
            start = i
    return runs


def episodes_from_lerobot(
    dataset: LeRobotDataset, mapping: dict[str, Any], episodes: set[int] | None = None, limit: int | None = None
) -> Iterator[dict[str, Any]]:
    """Yield TaskWitness episodes built from the dataset according to `mapping`."""
    validate_mapping(mapping, dataset)
    sensors, seg_spec, label_spec = mapping["sensors"], mapping.get("segments"), mapping.get("label")
    columns = sorted({s["column"] for s in sensors.values()} | {c["column"] for c in (seg_spec, label_spec) if c})
    info_digest = dataset.digest(dataset.root / "meta" / "info.json")
    produced = 0
    for info, data in dataset.frames(columns, episodes):
        ts = [float(_scalar(t)) for t in data["timestamp"]]
        task_text = [dataset.tasks.get(int(_scalar(i)), "") for i in data["task_index"]]
        if seg_spec:
            segments = [(_scalar(v), a, b) for v, a, b in _runs([_scalar(x) for x in data[seg_spec["column"]]])]
        else:
            segments = [(None, 0, len(ts))]
        for seg_id, a, b in segments:
            if "task_prefix" in mapping and not task_text[a].startswith(mapping["task_prefix"]):
                continue
            t0 = ts[a]
            streams = {}
            for stream, spec in sensors.items():
                field = STREAM_FIELDS[stream]
                streams[stream] = [{"t": round(t - t0, 6), field: value} for t, value in zip(ts[a:b], _convert(stream, spec, data[spec["column"]][a:b]))]
            eid = f"{dataset.root.name}-ep{info.index:06d}" + (f"-seg{seg_id}" if seg_id is not None else "")
            episode: dict[str, Any] = {
                "schema": EPISODE_SCHEMA,
                "episode_id": eid,
                "task": json.loads(json.dumps(mapping["task"])),
                "sensors": streams,
                "tags": {"lerobot_episode": info.index, "segment": seg_id if seg_id is not None else "", "task_text": task_text[a]},
                "provenance": {
                    "source": "lerobot",
                    "dataset": dataset.root.name,
                    "fps": dataset.fps,
                    "frames": [a, b],
                    "sources": {"meta/info.json": info_digest, info.data_file.name: dataset.digest(info.data_file)},
                },
            }
            if label_spec:
                column = [bool(_scalar(x)) for x in data[label_spec["column"]][a:b]]
                reduce = {"last": column[-1], "any": any(column), "all": all(column)}[label_spec.get("reduce", "last")]
                episode["label"] = {"verdict": "PASS" if reduce else "FAIL", "note": f"from column {label_spec['column']} ({label_spec.get('reduce', 'last')})"}
            yield episode
            produced += 1
            if limit is not None and produced >= limit:
                return
