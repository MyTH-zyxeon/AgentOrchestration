import json
import multiprocessing as mp
from pathlib import Path

from src.storage import JsonlEventLog


def _append_event(args):
    path, worker, index = args
    log = JsonlEventLog(Path(path))
    log.append({"worker": worker, "index": index})


def _read_records(path):
    records = []
    for log_path in sorted(path.parent.glob(f"{path.name}*")):
        if log_path.suffix == ".lock":
            continue
        for line in log_path.read_text(encoding="utf-8").splitlines():
            records.append(json.loads(line))
    return records


def test_concurrent_appenders_write_valid_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    args = [
        (str(path), worker, index)
        for worker in range(4)
        for index in range(20)
    ]

    with mp.Pool(4) as pool:
        pool.map(_append_event, args)

    records = _read_records(path)

    assert len(records) == len(args)
    assert {
        (record["worker"], record["index"])
        for record in records
    } == {
        (worker, index)
        for _, worker, index in args
    }


def test_rotation_preserves_complete_events(tmp_path):
    path = tmp_path / "events.jsonl"
    log = JsonlEventLog(path, max_bytes=120, backups=10)

    for index in range(12):
        log.append({"event": "task", "index": index, "payload": "x" * 20})

    records = _read_records(path)

    assert len(records) == 12
    assert {record["index"] for record in records} == set(range(12))


def test_malformed_record_count_stays_zero_under_stress(tmp_path):
    path = tmp_path / "events.jsonl"
    log = JsonlEventLog(path)

    for index in range(50):
        log.append({"index": index})

    records = _read_records(path)

    assert len(records) == 50
    assert log.malformed_record_count == 0
