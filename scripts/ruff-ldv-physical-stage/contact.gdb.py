"""Unscored, read-only hardware-address identity check executed inside GDB."""
import json
import os
from pathlib import Path
import gdb

subject = json.loads(Path(os.environ["LDV_CONTACT_INPUT"]).read_bytes())
gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set disable-randomization off")
gdb.execute("set startup-with-shell off")
gdb.execute("set auto-load safe-path /nonexistent-qa-gdb-autoload")
gdb.execute("set auto-solib-add off")
gdb.execute("starti")
pid = gdb.selected_inferior().pid
proc = Path("/proc") / str(pid)
assert (proc / "exe").samefile(subject["frontend"]["path"])
assert (proc / "cmdline").read_bytes().split(b"\0")[:-1] == [os.fsencode(a) for a in subject["argv"]]


def maps(info):
    rows = []
    for row in (proc / "maps").read_text().splitlines():
        parts = row.split(None, 5)
        if len(parts) != 6:
            continue
        span, perms, off, dev, ino, name = parts
        if int(ino) == info["inode"] and [int(p, 16) for p in dev.split(":")] == info["device"]:
            assert Path(name).samefile(info["path"])
            start, end = [int(n, 16) for n in span.split("-")]
            rows.append((start, end, perms, int(off, 16), name))
    return rows


gdb.execute("set stop-on-solib-events 1")
for _ in range(64):
    driver, llvm = maps(subject["driver"]), maps(subject["llvm"])
    if driver and llvm:
        break
    gdb.execute("continue")
else:
    raise RuntimeError("actual compiler libraries never loaded")
gdb.execute("set stop-on-solib-events 0")
zero = [row[0] for row in driver if row[3] == 0]
assert zero
page = os.sysconf("SC_PAGESIZE")
base = min(zero) - (subject["vaddr"] // page) * page
hits = {k: 0 for k in subject["symbols"]}
locations = {}


class Observe(gdb.Breakpoint):
    def __init__(self, kind, address):
        super().__init__("*" + hex(address), internal=True)
        self.kind = kind
        self.address_bound = address

    def stop(self):
        assert int(gdb.selected_frame().pc()) == self.address_bound
        hits[self.kind] += 1
        return False


watch = []
for kind, row in subject["symbols"].items():
    address = base + row["value"]
    assert any(lo <= address < hi and "x" in p for lo, hi, p, _, _ in driver)
    locations[kind] = [row["name"], address, row["value"]]
    watch.append(Observe(kind, address))
gdb.execute("continue")
code = int(gdb.parse_and_eval("$_exitcode"))
with Path(subject["output"]).open("x") as stream:
    json.dump({"exit": code, "pid": pid, "hits": hits, "addresses": locations,
               "driver_maps": driver, "llvm_maps": llvm, "loaded_bias": base}, stream, sort_keys=True)
