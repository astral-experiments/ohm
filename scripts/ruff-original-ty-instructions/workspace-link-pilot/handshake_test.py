"""Check the reader on the actual native staged-name publication boundary."""
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from coordinator import ready_pids

native = (HERE.parent / "e2e-existing-output/reuse.rs").read_text()
assert 'target.with_extension("pending")' in native
assert native.index("f.write_all(bytes)?") < native.index("std::fs::rename(staging, target)")
with tempfile.TemporaryDirectory() as temp:
    state = Path(temp)
    get = lambda seen=(), skipped=(): list(ready_pids(state, seen, skipped))
    ready = state / "ready-73"
    staged = ready.with_suffix(".pending")
    with staged.open("xb") as writer:
        assert get() == []
        writer.write(b"complete\n")
        writer.flush()
        assert get() == []
    assert get() == []
    os.replace(staged, ready)
    assert get() == ["73"] and get({"73"}) == [] and get((), {"73"}) == []
    ready.unlink()
    for name, body in [("ready-73", b"complete"), ("ready-X.pending", b"complete\n"), ("ready-73.pending.pending", b"complete\n")]:
        invalid = state / name
        invalid.write_bytes(body)
        try:
            get()
        except AssertionError:
            pass
        else:
            raise AssertionError("Unexpected native signal accepted: " + name)
        invalid.unlink()
print("Absent, open staging, complete staging, rename, duplicate, corrupt and unknown-name controls passed.")
