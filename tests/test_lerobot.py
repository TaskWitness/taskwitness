"""The LeRobot v3 adapter, on a small dataset laid out exactly like the real ones (checked on REASSEMBLE)."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from taskwitness import verify_episode  # noqa: E402
from taskwitness.cli import main  # noqa: E402
from taskwitness.integrations.lerobot import (  # noqa: E402
    LeRobotDataset,
    LeRobotError,
    episodes_from_lerobot,
    validate_mapping,
)

FPS = 30
TASKS = ["Pick round peg 2.", "Place round peg 2.", "Pick bolt 4."]
MAPPING = {
    "task": {"type": "grasp", "object": {"name": "peg", "width_m_min": 0.004, "width_m_max": 0.008}},
    "sensors": {"gripper_width": {"column": "observation.state.gripper_position", "index": 0, "field": "width_m"}},
    "segments": {"column": "segment.index"},
    "label": {"column": "segment.success", "reduce": "last"},
    "task_prefix": "Pick ",
}


def closing(final: float, frames: int = 60):
    """Fingers open at 0.04 m for half the frames, then stopped at `final`."""
    return [0.04] * (frames // 2) + [final] * (frames - frames // 2)


# (episode, file) -> list of segments: (task_index, success, finger widths)
LAYOUT = {
    (0, 0): [(0, True, closing(0.006)), (0, False, closing(0.0003)), (1, True, closing(0.03))],
    (1, 0): [(2, True, closing(0.007))],
    (2, 1): [(0, False, closing(0.04))],
}


def write_dataset(root: Path, version: str = "v3.0") -> Path:
    (root / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (root / "data" / "chunk-000").mkdir(parents=True)
    features = {
        "observation.state.gripper_position": {"dtype": "float32", "shape": [2]},
        "observation.load_cell": {"dtype": "float32", "shape": [1]},
        "observation.button": {"dtype": "float32", "shape": [1]},
        "observation.gripper": {"dtype": "float32", "shape": [1]},
        "segment.success": {"dtype": "bool", "shape": [1]},
        "segment.index": {"dtype": "int64", "shape": [1]},
        "observation.images.cam": {"dtype": "video", "shape": [48, 64, 3]},
        "timestamp": {"dtype": "float32", "shape": [1]},
    }
    (root / "meta" / "info.json").write_text(json.dumps({"codebase_version": version, "fps": FPS, "features": features,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"}))
    pq.write_table(pa.table({"task_index": list(range(len(TASKS))), "task": TASKS}), root / "meta" / "tasks.parquet")

    per_file: dict[int, list[dict]] = {0: [], 1: []}
    episode_rows, index = [], 0
    for (episode, file_index), segments in LAYOUT.items():
        start = index
        t = 0.0
        for seg_no, (task, success, widths) in enumerate(segments, start=1):
            for i, w in enumerate(widths):
                per_file[file_index].append({
                    "timestamp": t, "frame_index": index - start, "episode_index": episode, "index": index, "task_index": task,
                    "observation.state.gripper_position": [w, w], "observation.load_cell": [w * 1000.0],
                    "observation.button": [1.0 if i % 2 else 0.0], "observation.gripper": [0.04 if i < 30 else 0.001],
                    "segment.success": [success], "segment.index": [seg_no],
                })
                t += 1 / FPS
                index += 1
        episode_rows.append({
            "episode_index": episode, "tasks": sorted({TASKS[s[0]] for s in segments}), "length": index - start,
            "data/chunk_index": 0, "data/file_index": file_index, "dataset_from_index": start, "dataset_to_index": index,
            "videos/observation.images.cam/chunk_index": 0, "videos/observation.images.cam/file_index": 0,
            "videos/observation.images.cam/from_timestamp": start / FPS, "videos/observation.images.cam/to_timestamp": index / FPS,
        })
    for file_index, rows in per_file.items():
        if rows:
            pq.write_table(pa.Table.from_pylist(rows), root / "data" / "chunk-000" / f"file-{file_index:03d}.parquet")
    pq.write_table(pa.Table.from_pylist(episode_rows), root / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    return root


@pytest.fixture()
def dataset_root(tmp_path):
    return write_dataset(tmp_path / "tiny")


def test_dataset_reads_metadata_and_locates_shards(dataset_root):
    ds = LeRobotDataset(dataset_root)
    assert ds.fps == 30 and ds.tasks[0] == "Pick round peg 2."
    assert [e.index for e in ds.episodes] == [0, 1, 2]
    assert [e.data_file.name for e in ds.episodes] == ["file-000.parquet", "file-000.parquet", "file-001.parquet"]
    assert ds.episodes[0].tasks == ("Pick round peg 2.", "Place round peg 2.")


def test_segments_become_episodes_with_labels_filter_and_provenance(dataset_root):
    ds = LeRobotDataset(dataset_root)
    episodes = list(episodes_from_lerobot(ds, MAPPING))
    assert [e["episode_id"] for e in episodes] == ["tiny-ep000000-seg1", "tiny-ep000000-seg2", "tiny-ep000001-seg1", "tiny-ep000002-seg1"]
    assert [e["label"]["verdict"] for e in episodes] == ["PASS", "FAIL", "PASS", "FAIL"]  # the "Place" segment was filtered out
    first = episodes[0]
    assert first["sensors"]["gripper_width"][0] == {"t": 0.0, "width_m": pytest.approx(0.04)}
    assert first["sensors"]["gripper_width"][-1]["t"] == pytest.approx(59 / FPS, abs=1e-5)  # clock restarts at each segment
    assert first["tags"] == {"lerobot_episode": 0, "segment": 1, "task_text": "Pick round peg 2."}
    sources = first["provenance"]["sources"]
    file_digest = hashlib.sha256((dataset_root / "data/chunk-000/file-000.parquet").read_bytes()).hexdigest()
    assert sources["file-000.parquet"] == file_digest
    assert sources["meta/info.json"] == hashlib.sha256((dataset_root / "meta/info.json").read_bytes()).hexdigest()
    other = episodes[3]["provenance"]["sources"]  # episode 2 lives in the second shard, so only that shard is listed
    assert "file-000.parquet" not in other
    assert other["file-001.parquet"] == hashlib.sha256((dataset_root / "data/chunk-000/file-001.parquet").read_bytes()).hexdigest()


def test_converted_episodes_verify_against_their_labels(dataset_root):
    verdicts = [verify_episode(e)["verdict"] for e in episodes_from_lerobot(LeRobotDataset(dataset_root), MAPPING)]
    assert verdicts == ["PASS", "FAIL", "PASS", "FAIL"]  # held at 6 mm / closed on nothing / held at 7 mm / never closed


def test_subset_limit_and_no_segments(dataset_root):
    ds = LeRobotDataset(dataset_root)
    assert [e["tags"]["lerobot_episode"] for e in episodes_from_lerobot(ds, MAPPING, episodes={1, 2})] == [1, 2]
    assert len(list(episodes_from_lerobot(ds, MAPPING, limit=2))) == 2
    no_seg = {k: v for k, v in MAPPING.items() if k not in ("segments", "task_prefix")}
    whole = list(episodes_from_lerobot(ds, no_seg))
    assert [e["episode_id"] for e in whole] == ["tiny-ep000000", "tiny-ep000001", "tiny-ep000002"]
    assert whole[0]["label"]["verdict"] == "PASS"  # 'last' is the final frame's label: episode 0 ends in a successful place


def test_label_reductions(dataset_root):
    ds = LeRobotDataset(dataset_root)
    base = {k: v for k, v in MAPPING.items() if k not in ("segments", "task_prefix")}
    verdict = lambda reduce: [e["label"]["verdict"] for e in episodes_from_lerobot(ds, dict(base, label={"column": "segment.success", "reduce": reduce}))]  # noqa: E731
    assert verdict("any") == ["PASS", "PASS", "FAIL"]
    assert verdict("all") == ["FAIL", "PASS", "FAIL"]


def test_other_streams_convert_with_scale_index_and_thresholds(dataset_root):
    mapping = {
        "task": {"type": "place", "object": {"name": "block", "mass_g": 52.0}, "target_zone": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1}},
        "sensors": {
            "load_cell": {"column": "observation.load_cell", "field": "grams", "scale": 0.5},
            "button": {"column": "observation.button", "threshold": 0.5},
            "gripper": {"column": "observation.gripper", "open_above": 0.02},
        },
    }
    ep = next(episodes_from_lerobot(LeRobotDataset(dataset_root), mapping))
    assert ep["sensors"]["load_cell"][0]["grams"] == pytest.approx(40 * 0.5)
    assert [s["pressed"] for s in ep["sensors"]["button"][:4]] == [False, True, False, True]
    assert ep["sensors"]["gripper"][0]["state"] == "open" and ep["sensors"]["gripper"][-1]["state"] == "closed"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda m: m.pop("task"), "mapping.task"),
        (lambda m: m.update(sensors={}), "at least one stream"),
        (lambda m: m["sensors"].update(wheel={"column": "x"}), "unknown sensor stream"),
        (lambda m: m["sensors"]["gripper_width"].update(field="grams"), "must be 'width_m'"),
        (lambda m: m["sensors"]["gripper_width"].update(column="observation.nope"), "not in this dataset"),
        (lambda m: m.update(label={"column": "segment.success", "reduce": "median"}), "reduce"),
        (lambda m: m.update(colour="red"), "unknown mapping key"),
        (lambda m: m["sensors"].update(button={"column": "observation.button"}), "threshold"),
    ],
)
def test_bad_mappings_are_rejected(dataset_root, mutate, message):
    mapping = copy.deepcopy(MAPPING)
    mutate(mapping)
    with pytest.raises(LeRobotError, match=message):
        validate_mapping(mapping, LeRobotDataset(dataset_root))


def test_bad_datasets_are_rejected(tmp_path, dataset_root):
    with pytest.raises(LeRobotError, match="info.json is missing"):
        LeRobotDataset(tmp_path)
    old = write_dataset(tmp_path / "old", version="v2.1")
    with pytest.raises(LeRobotError, match="unsupported LeRobot dataset version"):
        LeRobotDataset(old)
    (dataset_root / "data/chunk-000/file-001.parquet").unlink()
    with pytest.raises(LeRobotError, match="data file .* is missing"):
        list(episodes_from_lerobot(LeRobotDataset(dataset_root), MAPPING))


def test_episode_split_across_the_file_is_refused(tmp_path):
    root = write_dataset(tmp_path / "tiny")
    path = root / "data/chunk-000/file-000.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[10]["episode_index"] = 1  # a frame of another episode in the middle of episode 0
    pq.write_table(pa.Table.from_pylist(rows), path)
    with pytest.raises(LeRobotError, match="not contiguous"):
        list(episodes_from_lerobot(LeRobotDataset(root), MAPPING, episodes={0}))


def test_video_span_gives_the_slice_of_the_concatenated_file(dataset_root):
    ds = LeRobotDataset(dataset_root)
    path, start, end = ds.video_span(1, "cam")
    assert path == dataset_root / "videos/observation.images.cam/chunk-000/file-000.mp4"
    assert (start, end) == pytest.approx((ds.episodes[1].meta["dataset_from_index"] / FPS, ds.episodes[1].meta["dataset_to_index"] / FPS))
    with pytest.raises(LeRobotError):
        ds.video_span(1, "wrist")


def test_cli_converts_then_evaluates(dataset_root, tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(MAPPING))
    out = tmp_path / "episodes"
    assert main(["lerobot", str(dataset_root), "--mapping", str(mapping), "--out", str(out)]) == 0
    assert len(list(out.glob("*.json"))) == 4
    assert main(["evaluate", str(out), "--out", str(tmp_path / "eval.json")]) == 0
    assert main(["lerobot", str(dataset_root), "--mapping", str(mapping), "--episodes", "0", "--limit", "1", "--out", str(tmp_path / "one")]) == 0
    assert len(list((tmp_path / "one").glob("*.json"))) == 1
    assert main(["lerobot", str(dataset_root), "--mapping", str(mapping), "--episodes", "9", "--out", str(tmp_path / "none")]) == 3
    assert main(["lerobot", str(dataset_root), "--mapping", str(mapping), "--episodes", "a-b", "--out", str(tmp_path / "bad")]) == 3
    assert main(["lerobot", str(tmp_path), "--mapping", str(mapping), "--out", str(tmp_path / "x")]) == 3


def test_read_video_slices_a_concatenated_file(tmp_path):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from taskwitness.vision import VisionError, read_video

    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for i in range(30):  # three "episodes" of one second; the grey level encodes the frame number
        writer.write(np.full((48, 64, 3), i * 8, dtype=np.uint8))
    writer.release()
    frames = list(read_video(str(path), start_s=1.0, end_s=2.0))
    assert len(frames) == 10
    assert [t for t, _ in frames] == pytest.approx([i / 10 for i in range(10)])
    assert int(frames[0][1].mean()) == pytest.approx(10 * 8, abs=6) and int(frames[-1][1].mean()) == pytest.approx(19 * 8, abs=6)
    assert len(list(read_video(str(path), start_s=2.5))) == 5
    with pytest.raises(VisionError):
        list(read_video(str(path), start_s=2.0, end_s=1.0))
