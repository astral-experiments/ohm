"""Exercise the exact cold-source projector, including true EOF and altered bytes."""

from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import probes


def dump(data):
    if not data:
        return "read(0, 0xff00, 0x20) = 0\n"
    return (f"read(0, 0xff00, 0x20) = {len(data):#x}\n | 00000  "
            + " ".join(f"{b:02x}" for b in data) + "   unrelated-ascii |\nread(0, 0xff00, 0x20) = 0\n")


with tempfile.TemporaryDirectory() as root_name:
    root = Path(root_name)
    trace = root / "trace"
    trace.mkdir()
    owner = root / "build-script-build"
    owner.write_bytes(b"known build-script test image")
    tree = {"parents": {100: 50, 103: 50, 106: 50}, "processes": [{"pid": 50, "path": str(owner)}]}
    def sample(salt, corruption=None):
        rs = []
        for i, (uuid, suffix, body) in enumerate(((salt * 16, "0", b""), ("f" * 16, "0", b""),
                                                   ("f" * 16, "1", b"fn probe() {}"))):
            pid = 100 + 3 * i
            name = "autocfg_" + uuid + "_" + suffix
            args = ["/sdk/rustc", "--crate-name", name, "--crate-type=lib", "--out-dir", "/out/" + str(int(i > 0)),
                    "--emit=llvm-ir", "-"]
            raw = dump(body)
            if i == 2:
                if corruption == "source":
                    raw = dump(b"fn alter() {}")
                if corruption == "argv":
                    args.insert(-1, "-Copt-level=1")
                if corruption == "nonce-outside":
                    args.insert(-1, "--cfg=" + name)
                if corruption == "no-eof":
                    raw = raw.splitlines(keepends=True)[0] + raw.splitlines(keepends=True)[1]
                if corruption == "short":
                    raw = raw.splitlines(keepends=True)[0]
            if i == 0 and corruption == "no-empty-read":
                raw = ""
            (trace / f"exec.{pid}").write_text(f"clone(flags=CLONE_FILES|CLONE_THREAD) = {pid + 1}\n")
            (trace / f"exec.{pid + 1}").write_text(raw)
            rs.append({"name": name, "argv": args, "kind": "full", "pid": pid})
        roster = {"rustc": [["full", r["name"], 1] for r in rs], "linkers": []}
        return probes.capture(root, rs, tree, roster, True)[0]
    baseline = sample("a")
    assert sample("b") == baseline
    for field in ("source", "argv"):
        assert sample("b", field) != baseline
    for field in ("nonce-outside", "no-eof", "short", "no-empty-read"):
        try:
            sample("b", field)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted " + field)
print("Verified nonce-only equivalence and true Rust input; rejected 6 input/argv changes.")
