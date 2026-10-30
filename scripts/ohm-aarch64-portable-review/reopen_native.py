"""Reopen a standalone replay's native records from its receipts directory or retained zip."""

import argparse
import gzip
import hashlib
import json
import runpy
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "replay/ohm-aarch64-linux"))
import qualify as q


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.raw.is_dir():
        read = lambda name: (args.raw / name).read_bytes()
    else:
        archive = zipfile.ZipFile(args.raw)
        assert archive.testzip() is None and len(archive.namelist()) == len(set(archive.namelist()))
        tail = "reviewed-native.json"
        target, = [n for n in archive.namelist() if n.split("/")[-1] == tail]
        archive_root = target[:-len(tail)]
        read = lambda name: archive.read(archive_root + name)

    proof = runpy.run_path(str(HERE / "replay/ohm-aarch64-confirm/complete-native-roster.py"))["inspect"]
    bundle = type("Input", (), {"read": staticmethod(read)})()
    enrolled = json.loads((HERE / "source/sdk-members.json").read_bytes())
    final = json.loads(read("reviewed-native.json"))
    role = "M" if final["role"] == "V" else final["role"]
    assert final["source"] == enrolled["roles"][role]["source"] and final["lock"] == q.LOCK
    assert final["driver_and_cargo"] == {
        Path(enrolled["driver_path"]).name: enrolled["roles"][role]["driver"][0],
        "cargo": enrolled["common"]["bin/cargo"][0],
    }
    assert set(final["phases"]) == {"old-empty", "edit", "unchanged-1", "unchanged-2", "invalid", "repair", "empty-edited"}
    semantic = {}
    for phase, facts in final["phases"].items():
        base = "review-history/" + phase
        observed = json.loads(read(base + "/native.json"))
        assert proof(bundle, base, observed) == facts["actual"]
        verified = json.loads(read(base + "/verified.json"))
        assert digest(read(base + "/native.json")) == verified["native"]
        assert sorted(facts["rustcs"]) == sorted(r["crate"] for r in observed["rustcs"])
        commands = ["cargo"] if phase == "invalid" else ["cargo", "reader-link", "qemu", "correct", "contrary"]
        for command in commands:
            prefix = base + "/" + command + "/"
            raw = json.loads(read(prefix + "command.json"))
            stdout = gzip.decompress(read(prefix + "stdout.gz"))
            stderr = gzip.decompress(read(prefix + "stderr.gz"))
            assert (digest(stdout), digest(stderr)) == (raw["stdout"], raw["stderr"])
            if command == "cargo":
                assert raw["argv"][-len(q.COMMAND):] == q.COMMAND
                _, roster, _, events = q.typed(stdout, phase != "invalid")
                assert roster == verified["typed"] and len(roster) == (38 if phase == "invalid" else 39)
                assert raw["exit"] == (101 if phase == "invalid" else 0)
                if phase == "invalid":
                    assert any(r.get("message", {}).get("code") and r["message"]["code"]["code"] == "E0425" for r in events)
            elif command == "contrary":
                assert raw["exit"] == 1 and any(r.get("code") and r["code"]["code"] == "E0308" for r in map(json.loads, stderr.splitlines()))
            else:
                assert raw["exit"] == 0
                if command == "qemu":
                    assert stdout.decode().strip() == facts["value"] == q.EXPECTED["old" if phase == "old-empty" else "new"]
        if phase == "invalid":
            assert facts["reader"] is None
            continue
        raw = read("objects/" + facts["reader"] + ".elf")
        assert digest(raw) == verified["reader"] == facts["reader"] and q.rt.elf(raw, (2, 3))
        rlib = read("objects/" + verified["archive"]["raw"] + ".rlib")
        assert q.archive(rlib) == verified["archive"]
        payloads = [[n, size, sha] for n, _, size, sha in verified["archive"]["objects"]]
        assert len(payloads) == 95
        semantic[phase] = [digest(raw), digest(json.dumps(payloads, separators=(",", ":")).encode())]
    assert semantic["old-empty"] != semantic["empty-edited"]
    assert all(value == semantic["empty-edited"] for phase, value in semantic.items() if phase != "old-empty")
    outcome = {"role": final["role"], "source": final["source"], "driver_and_cargo": final["driver_and_cargo"],
               "raw_terminal": digest(read("reviewed-native.json")), "commands": final["phases"], "native_sha256": semantic}
    encoded = (json.dumps(outcome, indent=2, sort_keys=True) + "\n").encode()
    if args.output:
        with args.output.open("xb") as f:
            f.write(encoded)
    print(digest(encoded))


if __name__ == "__main__":
    main()
