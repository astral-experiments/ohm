"""Independently read the Cargo transcripts and run their retained native executables."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def require(condition, why):
    if not condition:
        raise ValueError(why)


def read(path):
    return json.loads(path.read_bytes())


def raw(path):
    return gzip.decompress(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def body(path, sha, size, tmp, args, code, output, execute):
    data = raw(path)
    require(len(data) == size and digest(data) == sha, "retained executable changed")
    require(data[:4] in (b"\x7fELF", b"\xcf\xfa\xed\xfe"), "unknown native file magic")
    if execute:
        exe = tmp / sha
        if not exe.exists():
            exe.write_bytes(data)
            exe.chmod(0o700)
        child = subprocess.run([exe, *args], capture_output=True, timeout=15)
        require(child.returncode == code and output in child.stdout, "different native execution")


def worktree(folder, fixed, tmp, execute):
    report = read(folder / "complete.json")
    for key, phase in (("alias", "register-alias"), ("sibling", "register-valid")):
        entry = read(folder / phase / "ledger.json")
        require(entry == report[key] and read(folder / phase / "exit.json") == entry["status"], phase)
        if key == "sibling":
            require(entry["status"] == 0 and len(entry["after"]) == 2 and not entry["nested"], phase)
        elif fixed:
            require(entry["status"] == 101 and not entry["nested"] and entry["before"] == entry["after"], phase)
    for spelling in ("attached", "split", "default"):
        for phase in ("build", "repeat", "invalid", "repair"):
            path = folder / spelling / phase
            row = read(path / "verdict.json")
            require(row == report["cases"][spelling][phase], "inconsistent phase")
            argv = read(path / "invocation.json")["argv"]
            require(Path(argv[0]).name == "cargo" and argv[1:] == ["+ohm", "build", "--offline", "--message-format=json"], "different Cargo invocation")
            js = [json.loads(line) for line in raw(path / "stdout.gz").splitlines()]
            ok = phase != "invalid"
            require(js[-1] == {"reason": "build-finished", "success": ok}
                    and read(path / "exit.json") == row["status"] == (0 if ok else 101), "wrong Cargo exit")
            prefix = row["prefix"]
            require(prefix == ("/ohm-workspace/v7" if spelling == "default" else "/ohm-requested-sources")
                    or (not fixed and prefix == "/ohm-workspace/v7"), "incorrect source name")
            source = prefix + "/src/location.rs"
            if not ok:
                (msg,) = [x["message"] for x in js if x.get("reason") == "compiler-message" and x["message"]["level"] == "error"]
                require(msg["message"] == "requested source " + source and
                        [s["file_name"] for s in msg["spans"] if s["is_primary"]] == [source], "incorrect primary diagnostic")
                continue
            (artifact,) = [x for x in js if x.get("reason") == "compiler-artifact" and x["target"]["name"] == "path_witness"]
            require(artifact["fresh"] == row["fresh"] == (phase == "repeat"), "wrong freshness")
            run = path.with_name(phase + "-native")
            expected = (source + "|29\n").encode()
            require(raw(run / "stdout.gz") == expected and not raw(run / "stderr.gz") and
                    read(run / "exit.json") == 0 and read(run / "invocation.json")["argv"] == [artifact["executable"]], "wrong file! result")
            body(folder / "bodies" / (row["elf"] + ".gz"), row["elf"], row["bytes"], tmp, [], 0, expected, execute)


def terminal(folder, tmp, execute):
    report = read(folder / "complete.json")
    require(report["source"] == "aed63f3c04ca7fb3eb4826bc53125d9dc741d23d1a6f75ec66cf4017ad3b50b8" and
            report["lib"] == "29387fe4112079ffc2afcf2de2f7ecb37e2b397abb56a58102021c04602943b7", "different native test fixture")
    for mode in ("default", "enabled"):
        path = folder / mode
        row = report["cases"][mode]
        argv = read(path / "terminal-argv.json")
        require(argv[:2] == ["cargo", "+ohm"] and argv[-3:] == ["--", "--exact", "selected"] and
                ("-Zohm-ready-tests" in argv) == (mode == "enabled"), "different foreground command")
        state = read(path / "terminal-start.json")
        require(dict(state, status=0) == row["terminal"] and
                ("--ohm-ready-test-relay" in state["group_command"].split()) == (mode == "enabled"), "different foreground group")
        stdout = raw(path / "terminal.gz").replace(b"\r\n", b"\n")
        require(b"1 passed; 0 failed" in stdout and b"\nOHM-CARGO=0\n" in stdout, "foreground test failed")
        require(read(path / "no-run/exit.json") == 0 and b"Executable unittests" in raw(path / "no-run/stderr.gz"), "no-run failed")
        require(read(path / "rejected/exit.json") == 101 and b"the test filter was lost" in raw(path / "rejected/stdout.gz"), "missing negative verdict")
        body(path / "native.gz", row["native"], row["bytes"], tmp, ["--list"], 0, b"excluded: test\nselected: test\n", execute)
        body(path / "native.gz", row["native"], row["bytes"], tmp, ["--exact", "excluded"], 101, b"the test filter was lost", execute)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    parser.add_argument("--bytes-only", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        for name, roles in [("slot-worktree-paths", ["historical", "published-22", "rebased"]),
                            ("slot-ready-terminal", ["published-22", "rebased"])]:
            base = args.reports / name
            runs = read(base / "complete.json")["roles"]
            require(set(runs) == set(roles), "missing source role")
            for role in roles:
                folder = base / role
                require(digest((folder / "complete.json").read_bytes()) == runs[role], "different source role")
                if name == "slot-worktree-paths":
                    worktree(folder, role == "rebased", Path(tmp), not args.bytes_only)
                else:
                    terminal(folder, Path(tmp), not args.bytes_only)
                print(name, role, runs[role])


if __name__ == "__main__":
    main()
