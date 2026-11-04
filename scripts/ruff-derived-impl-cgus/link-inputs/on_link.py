"""Reopen one genuine in-flight Wild argv at its original paths, outside all counters."""

import ast
import fcntl
import gzip
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from objects import archives, digest, layout, require, sha
from opaque import challenge

WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
Q = re.compile(r'"(?:[^"\\]|\\.)*"')
OPEN = re.compile(r"^(?:open|openat|openat2)\(.*\)\s+=\s+(\d+)<([^>]+)>$")
MAPPED = re.compile(r"^mmap\(.*,\s*\d+<([^>]+)>,\s*[^,]+\)\s+=\s+0x")
BAD = re.compile(r"^([a-z0-9_]+)\(.*\)\s+=\s+-1 (ENOENT|ENOTDIR|EACCES)\b")


def encode(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    body = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path.suffix == ".gz":
        body = gzip.compress(body, compresslevel=3, mtime=0)
    if path.exists():
        require(path.read_bytes() == body, "conflicting custody " + str(path))
    else:
        path.write_bytes(body)


def strong(path, roots, archive_dir):
    physical = path.resolve(strict=True)
    require(
        any(physical.is_relative_to(r) for r in roots),
        "out-of-scope native input " + str(physical),
    )
    before = physical.stat()
    require(
        stat.S_ISREG(before.st_mode) and before.st_size <= 800 << 20,
        "unexpected input kind/size",
    )
    file_hash = digest(physical)
    record = {
        "real": str(physical),
        "bytes": before.st_size,
        "sha256": file_hash,
        "stat": [before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns],
    }
    with physical.open("rb") as file:
        magic = file.read(8)
    require(magic != b"!<thin>\n", "unbounded thin archive " + str(path))
    if magic == b"!<arch>\n":
        table = archive_dir / (file_hash + ".json.gz")
        if table.is_file():
            rows = json.loads(gzip.decompress(table.read_bytes()))
        else:
            rows = archives(physical)
            if rows is not None:
                encode(table, rows)
        if rows is not None:
            record["archive"] = file_hash
    require(
        path.resolve(strict=True) == physical, "lexical input retargeted during read"
    )
    after = physical.stat()
    require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        "input changed during digest " + str(path),
    )
    return record


def price_free_fds(env, fdsource):
    flags = env.get("CARGO_MAKEFLAGS", env.get("MAKEFLAGS", ""))
    require("--jobserver-auth=fifo:" not in flags, "undeclared FIFO jobserver")
    pairs = {
        tuple(map(int, p))
        for p in re.findall(r"--jobserver-(?:auth|fds)=(\d+),(\d+)", flags)
    }
    if not pairs:
        return ()
    require(len(pairs) == 1, "ambiguous jobserver")
    rd, wr = pairs.pop()
    seen = {
        int(t[0]): (int(t[1]), t[2])
        for line in fdsource.splitlines()
        if (t := line.split(" ", 2))
    }
    if rd not in seen and wr not in seen:
        return ()
    require(
        rd in seen
        and wr in seen
        and seen[rd][1] == seen[wr][1]
        and seen[rd][1].startswith("pipe:[")
        and 0 <= seen[rd][0] <= 256,
        "unbound original jobserver",
    )
    a, b = os.pipe()
    x, y = [fcntl.fcntl(f, fcntl.F_DUPFD_CLOEXEC, max(rd, wr, 63) + 1) for f in (a, b)]
    os.close(a)
    os.close(b)
    os.write(y, b"+" * seen[rd][0])
    os.dup2(x, rd, inheritable=True)
    os.dup2(y, wr, inheritable=True)
    os.close(x)
    os.close(y)
    return rd, wr


def parse_trace(private, public):
    opened = set()
    mapped = set()
    negative = set()
    trace = []
    for f in sorted(private.glob("io.*")):
        require(
            f.is_file() and f.stat().st_size < 128 << 20, "invalid linker syscall trace"
        )
        for line in f.read_text().splitlines():
            if line.startswith(("execve(", "execveat(")):
                # Outside argv, the execve line may include environment data. Never retain it.
                continue
            match = OPEN.match(line)
            if match:
                opened.add(match[2])
            match = MAPPED.match(line)
            if match:
                mapped.add(match[1])
            match = BAD.match(line)
            if match:
                quoted = Q.search(line)
                if quoted:
                    value = ast.literal_eval(quoted[0])
                    negative.add((match[1], value, match[2]))
            trace.append(line)
    require(trace and opened and mapped, "incomplete native syscall realization")
    raw = ("".join(s + "\n" for s in trace)).encode()
    (public / "native-syscalls.txt.gz").write_bytes(
        gzip.compress(raw, compresslevel=3, mtime=0)
    )
    return opened, mapped, sorted(negative)


def main(private, public, name):
    actor = private / name
    root = public / name
    root.mkdir()
    config = json.loads((private / "policy.json").read_bytes())
    cwd = Path((actor / "cwd").read_text())
    require(cwd.is_dir(), "missing original cwd")
    environment = (actor / "env.nul").read_bytes().split(b"\0")
    require(environment.pop() == b"", "invalid environment")
    env = {
        os.fsdecode(k): os.fsdecode(v)
        for item in environment
        for k, v in [item.split(b"=", 1)]
    }
    require(
        len(env) == len(environment)
        and not set(env)
        & {
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "LD_PRELOAD",
            "WILD_WRITE_LAYOUT",
            "WILD_SAVE_DIR",
            "WILD_SAVE_BASE",
            "WILD_SAVE_SKIP_LINKING",
        },
        "unexpected original observer environment",
    )
    elements = (actor / "argv.nul").read_bytes().split(b"\0")
    require(elements.pop() == b"" and all(elements), "incomplete command line")
    argv = list(map(os.fsdecode, elements))
    linker = Path(argv[0])
    require(
        digest(linker) == WILD and argv.count("-o") == 1,
        "different signed linker/command",
    )
    at = argv.index("-o") + 1
    actual = Path(argv[at])
    require(
        actual.is_absolute()
        and actual.name == name
        and actual.parent.resolve().is_relative_to(Path(config["target"]).resolve()),
        "unregistered linker output",
    )
    roots = [Path(s).resolve() for s in config["roots"]]
    ephemeral = []
    for word in argv:
        # GCC creates this named response to its LTO plugin even when Wild does not consume it.
        if word.startswith("-plugin-opt=-fresolution="):
            path = Path(word.split("=", 2)[2])
            require(
                str(path.parent) == "/tmp"
                and re.fullmatch(r"cc[A-Za-z0-9_]+[.]res", path.name),
                "unrecognized resolution path",
            )
            if path.is_file():
                require(
                    not path.is_symlink()
                    and path.stat().st_uid == os.getuid()
                    and path.stat().st_size < 16 << 20,
                    "unowned resolution input",
                )
                roots.append(path)
            ephemeral.append(str(path))
    output = actor / "physical-projection"
    args = argv.copy()
    args[at] = str(output)
    require(
        not any(s.startswith("@") for s in argv),
        "response file needs a separate physical parser",
    )
    if config.get("tiny"):
        require(len(argv) > 6, "empty smoke link")
    else:
        require(
            "-plugin" in argv
            and "--gc-sections" in argv
            and any(v.endswith(".rlib") for v in argv),
            "unexpected Ruff link surface",
        )
    pipes = price_free_fds(env, (actor / "fds").read_text())
    free = shutil.disk_usage(actor).free
    require(
        free > 15 * 2**30 and not output.exists(), "storage or private output reused"
    )
    checkenv = env | {"WILD_WRITE_LAYOUT": "1"}
    cmd = [
        "strace",
        "-ff",
        "-qq",
        "-yy",
        "-s",
        "8192",
        "-e",
        "trace=%file,mmap",
        "-o",
        str(actor / "io"),
        "--",
        *args,
    ]
    with (actor / "out").open("xb") as so, (actor / "err").open("xb") as se:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=checkenv,
            pass_fds=pipes,
            stdout=so,
            stderr=se,
            timeout=300,
            check=False,
        )
    require(
        result.returncode == 0 and output.is_file(),
        "signed Wild replay "
        + str(result.returncode)
        + " "
        + (actor / "err").read_text(errors="replace")[-800:],
    )
    image = {"bytes": output.stat().st_size, "sha256": digest(output)}
    lp = Path(str(output) + ".layout")
    rows, thunks = layout(lp)
    opened, mapped, negative = parse_trace(actor, root)
    archive_dir = public.parent / "archive-members"
    archive_dir.mkdir(exist_ok=True)
    inputs = {}
    other = {}

    def bind(word, why):
        path = Path(word)
        if not path.is_absolute():
            path = cwd / path
        word = str(path)
        if path == output or path == lp or path.is_relative_to(actor):
            kind = "private-diagnostic"
        elif any(path.is_relative_to(Path(t)) for t in ("/proc", "/sys", "/dev")):
            kind = "kernel-or-device"
        elif path.is_dir():
            kind = "directory"
        elif not path.exists():
            kind = "no-longer-present"
        elif not path.is_file():
            kind = "special"
        else:
            kind = None
        if kind is not None:
            other.setdefault(word, set()).add(kind + ":" + why)
            require(
                kind != "no-longer-present"
                or why not in ("successful-open", "file-backed-mmap", "Wild-layout"),
                "lost opened native input " + word,
            )
            return
        if word not in inputs:
            inputs[word] = strong(path, roots, archive_dir) | {"observed": []}
        if why not in inputs[word]["observed"]:
            inputs[word]["observed"].append(why)

    for word in sorted(opened):
        bind(word, "successful-open")
    for word in sorted(mapped):
        bind(word, "file-backed-mmap")
    for k, word in enumerate(argv):
        if k in (0, at):
            continue
        if word.startswith("/") and Path(word).exists() and Path(word).is_file():
            bind(word, "argv")
        if word.startswith("-plugin-opt="):
            path = word.split("=")[-1]
            if path.startswith("/") and Path(path).is_file():
                bind(path, "plugin-option")
    bind(str(linker), "signed-executable")
    elf = subprocess.check_output(["readelf", "-lW", linker], text=True)
    interp = re.findall(r"Requesting program interpreter: ([^\]]+)\]", elf)
    for name_ in interp:
        bind(name_, "PT_INTERP")
    parsed = {}
    for disk, member, _, _, _, _, _ in rows:
        bind(disk, "Wild-layout")
        if member:
            path = Path(disk)
            key = str(path if path.is_absolute() else cwd / path)
            require(
                key in inputs and "archive" in inputs[key],
                "unbound archive layout " + disk,
            )
            h = inputs[key]["archive"]
            if h not in parsed:
                table = json.loads(
                    gzip.decompress((archive_dir / (h + ".json.gz")).read_bytes())
                )
                parsed[h] = {(v[1], v[2]): (v[0], v[3]) for v in table}
            start, end, member_name = member
            require(
                (start, end) in parsed[h] and parsed[h][start, end][0] == member_name,
                "unbound linker-selected member " + str((disk, member)),
            )
            member.append(parsed[h][start, end][1])
    (root / "layout.bin.gz").write_bytes(
        gzip.compress(lp.read_bytes(), compresslevel=3, mtime=0)
    )
    encode(root / "inputs.json.gz", inputs)
    encode(root / "layout.json.gz", rows)
    encode(
        root / "receipt.json",
        {
            "argv": argv,
            "cwd": str(cwd),
            "environment_sha256": sha((actor / "env.nul").read_bytes()),
            "wild": WILD,
            "input_roots": config["roots"],
            "standalone": image,
            "output_argv_slot": at,
            "expanded_response_files": [],
            "raw_layout": digest(lp),
            "layout_records": len(rows),
            "thunks": thunks,
            "special_observations": {k: sorted(v) for k, v in other.items()},
            "ephemeral_resolution_options": ephemeral,
            "opened": sorted(opened),
            "mapped": sorted(mapped),
            "failed_file_probes": negative,
            "kernel_interpreter": interp,
        },
    )
    # Only the explicitly admitted active target and a bounded private replay can be removed.
    require(output.parent == actor and lp.parent == actor, "unexpected private outputs")
    output.unlink()
    lp.unlink()
    for f in actor.glob("io.*"):
        f.unlink()
    if name == config.get("native_shadow_target"):
        encode(
            root / "opaque-native.json",
            challenge(actor, argv, at, cwd, env, pipes, image),
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
