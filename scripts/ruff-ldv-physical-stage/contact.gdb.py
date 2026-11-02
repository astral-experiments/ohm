"""Unscored, read-only hardware-address identity check executed inside GDB."""
import hashlib
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
        if not name.startswith("/") or name.endswith(" (deleted)") or int(ino) == 0:
            continue  # glibc can name a distinct anonymous BSS after the DSO.
        rooted = proc / "root" / name.lstrip("/")
        if not rooted.samefile(info["path"]):
            continue
        st = rooted.stat()
        assert st.st_ino == info["inode"] and [os.major(st.st_dev), os.minor(st.st_dev)] == info["device"], (name, st.st_ino, info)
        start, end = [int(n, 16) for n in span.split("-")]
        rows.append((start, end, perms, int(off, 16), name, dev, int(ino)))
    return rows


def register(name):
    return int(gdb.parse_and_eval("$" + name)) & ((1 << 64) - 1)


def live(lo, length):
    return bytes(gdb.selected_inferior().read_memory(lo, length))


def check_id(rows, info):
    note = info["build_id"]
    if note is None:
        return None
    wanted = bytes.fromhex(note["hex"])
    for lo, hi, perms, offset, *_ in rows:
        adr = lo + note["offset"] - offset
        if "r" in perms and lo <= adr and adr + len(wanted) <= hi:
            actual = live(adr, len(wanted))
            assert actual == wanted, ("different live ELF note", info["path"], actual.hex(), wanted.hex())
            return [adr, actual.hex()]
    raise AssertionError(("GNU build ID not present in an actual file-backed read mapping", info["path"]))


# The original hosted refusal did not distinguish a layered maps device from an
# anonymous side segment. Bind the actual successful PROT_EXEC mmap to its still-
# open loader FD and independently match the live note and instruction bytes.
# No pathname-only match and no tracing of a measured Cargo command is accepted.
gdb.execute("catch syscall mmap", to_string=True)
trap = gdb.breakpoints()[-1]
backed = {k: {} for k in ("driver", "llvm")}
for _ in range(1024):
    gdb.execute("continue", to_string=True)
    if not (proc / "maps").exists():
        raise AssertionError(("inferior exited before both loader fds were proven", sorted(backed)))
    address, prot, fd, off, size = map(register, ("rax", "rdx", "r8", "r9", "rsi"))
    if address >= (1 << 63) or not (prot & 4) or fd > 1 << 20:
        continue
    opened = proc / "fd" / str(fd)
    st = opened.stat()
    for kind in ("driver", "llvm"):
        info = subject[kind]
        if not opened.samefile(info["path"]):
            continue
        assert st.st_ino == info["inode"] and [os.major(st.st_dev), os.minor(st.st_dev)] == info["device"], ("wrong actual loader fd", kind, info)
        with opened.open("rb") as obj:
            h = hashlib.sha256()
            while chunk := obj.read(1 << 20):
                h.update(chunk)
            assert h.hexdigest() == info["sha256"], ("different actual mmap input bytes", kind)
            mapping, = (row for row in maps(info) if row[0] <= address < row[1] and "x" in row[2]
                        and row[3] + address - row[0] == off)
            chunk = min(64, size, mapping[1] - address)
            obj.seek(off)
            assert chunk >= 16 and live(address, chunk) == obj.read(chunk), ("different mapped code", kind)
        for seg in info["exec_loads"]:
            low = seg["offset"]
            if not (off <= low and low + seg["size"] <= off + size):
                continue
            here = address + low-off
            entry = {"fd": fd, "returned_address": address, "length": size, "file_offset": off,
                     "prot": prot, "file_sha": h.hexdigest(), "fd_inode": [st.st_dev, st.st_ino],
                     "kernel_row": mapping,"segment":seg,"address":here}
            hmem = hashlib.sha256()
            for cursor in range(0,seg["size"],1<<20):
                hmem.update(live(here+cursor,min(1<<20,seg["size"]-cursor)))
            entry["actual_rx_sha256"] = hmem.hexdigest()
            assert entry["actual_rx_sha256"] == seg["sha256"], ("different loaded executable segment",kind,low)
            backed[kind][str(low)] = entry
    if all(len(backed[k])==len(subject[k]["exec_loads"]) for k in backed):
        break
else:
    raise AssertionError(("loader did not mmap all registered executable regions", backed))
trap.delete()
driver, llvm = maps(subject["driver"]), maps(subject["llvm"])
fdproof={}
for kind, rows in (("driver", driver), ("llvm", llvm)):
    segs=list(backed[kind].values())
    assert set(backed[kind])=={str(s["offset"]) for s in subject[kind]["exec_loads"]}
    fdproof[kind]={"segments":segs,"mapped_build_id":check_id(rows,subject[kind]),
                   "file_sha":segs[0]["file_sha"],"fd_inode":segs[0]["fd_inode"]}
bias={s["address"]-s["segment"]["vaddr"] for s in fdproof["driver"]["segments"]}
assert len(bias)==1
base=bias.pop()
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
    selected, = (r for r in driver if r[0] <= address and address + 16 <= r[1] and "x" in r[2])
    assert any(s["address"] <= address and address+16 <= s["address"]+s["segment"]["size"]
               for s in fdproof["driver"]["segments"])
    with open(subject["driver"]["path"], "rb") as binary:
        binary.seek(selected[3] + address - selected[0])
        assert live(address, 16) == binary.read(16), ("pass address differs from actual installed ELF", kind)
    locations[kind] = [row["name"], address, row["value"]]
    watch.append(Observe(kind, address))
gdb.execute("continue")
code = int(gdb.parse_and_eval("$_exitcode"))
with Path(subject["output"]).open("x") as stream:
    json.dump({"exit": code, "pid": pid, "hits": hits, "addresses": locations,
               "driver_maps": driver, "llvm_maps": llvm, "loaded_bias": base, "loader_fds": fdproof}, stream, sort_keys=True)
