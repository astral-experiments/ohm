"""Exercise reaped and detached descendants through the exact full-command resource meter."""

import json, os, subprocess, sys, time
from pathlib import Path


def child(path):
    block = b"\xfe" * (1 << 20)
    with path.open("xb", buffering=0) as f:
        for _ in range(3):
            assert f.write(block) == len(block)
        os.fsync(f.fileno())
    with path.open("rb") as f:
        assert f.read() == block * 3


def payload(root):
    first = os.fork()
    if first == 0:
        grand = os.fork()
        if grand == 0:
            time.sleep(0.20)
            child(root / "detached")
            os._exit(0)
        child(root / "waited")
        os._exit(0)
    assert os.waitpid(first, 0)[1] == 0


def run(exe, root, hardware):
    root.mkdir()
    record = root / "meter.json"
    ret = subprocess.run(
        [
            exe,
            record,
            sys.executable,
            sys.executable,
            "-IB",
            __file__,
            "--payload",
            root,
        ],
        check=False,
    )
    assert ret.returncode == 0, ret.returncode
    data = json.loads(record.read_bytes())
    assert (
        data["status"] == 0 and data["reaped"] == 2 and data["elapsed_ns"] > 160_000_000
    )
    assert (
        data["user_us"] > 0
        and data["system_us"] > 0
        and data["wchar"] >= 6 << 20
        and data["rchar"] >= 6 << 20
    )
    assert data["write_bytes"] >= 6 << 20 and data["outblock"] >= 6 * (1 << 20) // 512
    assert (
        data["minflt"] > 0
        and data["syscr"] > 0
        and data["syscw"] > 0
        and data["maxrss_kib"] > 0
    )
    assert (
        (root / "waited").stat().st_size
        == (root / "detached").stat().st_size
        == 3 << 20
    )
    if hardware:
        assert data["instructions"] > 0 and data["enabled"] == data["running"] > 0
    print(json.dumps(data, sort_keys=True))
    for f in ("waited", "detached"):
        (root / f).unlink()
    return data


if __name__ == "__main__":
    if sys.argv[1] == "--payload":
        payload(Path(sys.argv[2]))
    else:
        run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "hardware")
