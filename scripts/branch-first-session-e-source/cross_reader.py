"""Check both compiler generations against one physical incremental cache and a clean ELF."""

import gzip
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject as s
from native_trace import original_calls
from registration import need, sha, write

NAMES = ("dep-graph.bin", "query-cache.bin")
DENIAL = b"we asserted that an existing incremental cache directory should be successfully loaded, but it was not"


def sessions(cache):
    if not cache.exists():
        return set()
    crates = [p for p in cache.iterdir() if p.is_dir()]
    need(len(crates) == 1 and not crates[0].is_symlink(), "wrong incremental crate")
    dirs = {p for p in crates[0].iterdir() if p.is_dir()}
    need(
        all(
            p.name.startswith("s-") and not p.name.endswith("-working") and not p.is_symlink()
            for p in dirs
        ),
        "incomplete session",
    )
    return dirs


def tables(source, mode, out):
    result = {}
    for name, tag in zip(NAMES, b"GQ", strict=True):
        raw = source / name
        packed = source / ("ohm-packed-" + name)
        actual, absent = (packed, raw) if mode == "packed" else (raw, packed)
        need(
            actual.is_file() and not actual.is_symlink() and not absent.exists(),
            "wrong table representation in " + str(source),
        )
        payload = actual.read_bytes()
        if mode == "packed":
            z = zlib.decompressobj()
            data = z.decompress(payload) + z.flush()
            prefix = data[11:].index(0) + 11
            need(
                z.eof
                and not z.unused_data
                and not z.unconsumed_tail
                and data[:2] == bytes((1, tag))
                and data[2] & 1
                and data[2] < 8
                and data[11:prefix].decode() == source.name.rsplit("-", 1)[0],
                "wrong raw source session",
            )
            size = int.from_bytes(data[3:11], "little")
            payload = data[prefix + 1 :]
            need(len(payload) == size, "truncated native table")
        need(
            payload.startswith(b"RSIC") and 64 << 10 <= len(payload) <= 16 << 20,
            "missing real RSIC table",
        )
        st = actual.stat()
        result[name] = {
            "path": str(actual),
            "sha256": sha(actual),
            "bytes": st.st_size,
            "dev": st.st_dev,
            "ino": st.st_ino,
            "decoded_sha256": hashlib.sha256(payload).hexdigest(),
            "decoded_bytes": len(payload),
        }
        (out / (actual.name + ".gz")).write_bytes(
            gzip.compress(actual.read_bytes(), compresslevel=1, mtime=0)
        )
    return result


def kernel(directory, stem, driver, mode, donor, returned, marker, *, reopen=False):
    """Bind successful reads, mappings and the marker link to threads of the actual loaded rustc image."""
    from functools import lru_cache

    parent, transitions, probes, mapped = {}, {}, [], []
    work = returned.with_name(returned.name.rsplit("-", 1)[0] + "-working")

    def fd_mmap(line, path):
        return (
            line.startswith("mmap(")
            and "<" + str(path) + ">" in line
            and re.search(r"= 0x[0-9a-f]+$", line)
        )

    def link(line, old, new):
        return (
            line.startswith(("link(", "linkat("))
            and '"' + str(old) + '"' in line
            and '"' + str(new) + '"' in line
            and re.search(r"\)\s+= 0$", line)
        )

    names = sorted(
        directory.glob(stem.name + ".*.gz") if reopen else stem.parent.glob(stem.name + ".*")
    )
    for fp in names:
        original = Path(fp.stem) if reopen else fp
        pid = int(original.suffix[1:])
        raw = gzip.decompress(fp.read_bytes()).decode() if reopen else fp.read_text()
        if not reopen:
            (directory / (fp.name + ".gz")).write_bytes(
                gzip.compress(raw.encode(), compresslevel=1, mtime=0)
            )
        changes = []
        for idx, (kind, line) in enumerate(original_calls(raw.splitlines())):
            if kind != "call":
                changes.append((idx, False))
                continue
            if line.startswith(("execve(", "execveat(")) and re.search(r"= 0$", line):
                changes.append((idx, False))
            if fd_mmap(line, driver) and "PROT_EXEC" in line:
                mapped.append([pid, idx, line])
                changes.append((idx, True))
            clone = re.match(r"^(clone3?|fork|vfork)\(.*\)\s+= (\d+)$", line)
            if clone:
                child = int(clone[2])
                need(child not in parent and child != pid, "ambiguous tracee birth")
                parent[child] = (pid, idx, "CLONE_THREAD" in line)
            if link(line, marker, work / marker.name):
                probes.append(("marker", pid, idx, line))
            for name in NAMES:
                path = donor[name]["path"]
                if fd_mmap(line, work / name) and line.startswith(
                    f"mmap(NULL, {donor[name]['decoded_bytes']}, PROT_READ, MAP_PRIVATE,"
                ):
                    probes.append(("mapped-" + name, pid, idx, line))
                if mode == "packed":
                    good = (
                        line.startswith(("read(", "pread64("))
                        and "<" + path + ">" in line
                        and re.search(r"\)\s+= [1-9][0-9]*$", line)
                    )
                else:
                    good = link(line, path, work / name)
                if good:
                    probes.append((name, pid, idx, line))
        transitions[pid] = changes
        if not reopen:
            fp.unlink()

    @lru_cache(maxsize=None)
    def owner(pid, idx):
        previous = [flag for change, flag in transitions.get(pid, []) if change < idx]
        if previous:
            return previous[-1]
        if pid not in parent:
            return False
        creator, event, thread = parent[pid]
        return thread and owner(creator, event)

    earned = {}
    for key, pid, idx, line in probes:
        if owner(pid, idx):
            earned.setdefault(key, []).append([pid, idx, line])
    required = {"marker", *NAMES, *("mapped-" + n for n in NAMES)}
    need(
        mapped and set(earned) == required,
        "missing owned cache inputs, decoded mmap or source marker link",
    )
    return {"driver_mapping": mapped, "owned_operations": earned}


def src(value):
    # Same 384 ordinary public definitions, native static and CGU setup as the native product run-make.
    return (
        "#![allow(dead_code)]\n"
        + "".join(f"pub fn f{i}(x:u32)->u32 {{ x.wrapping_add({i}) }}\n" for i in range(384))
        + f"static DATA:[u8;32768]=[{value};32768];\n"
        + 'fn main(){let n=f0(std::hint::black_box(&DATA)[0].into());println!("{n}"); '
        'if std::env::var("EXPECT").unwrap().parse::<u32>().unwrap()!=n{std::process::exit(19)}}\n'
    )


def command(args, work, env, folder, code=0):
    proc = subprocess.run(list(map(str, args)), cwd=work, env=env, capture_output=True)
    folder.mkdir()
    (folder / "stdout").write_bytes(proc.stdout)
    (folder / "stderr").write_bytes(proc.stderr)
    write(
        folder / "command.json",
        {"cwd": str(work), "argv": list(map(str, args)), "code": proc.returncode},
    )
    need(proc.returncode == code, str(folder) + " returned " + str(proc.returncode))
    return proc


def fixture(work):
    work.mkdir()

    def git(*args):
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=qa@invalid.example",
                "-c",
                "user.name=QA",
                "-c",
                "commit.gpgsign=false",
                "-C",
                work,
                *args,
            ],
            check=True,
        )

    git("init", "-q", "--template=", "-b", "cross-A")
    for branch, value in (("cross-A", 17), ("cross-B", 29)):
        if value == 29:
            git("switch", "-qc", branch)
        (work / "main.rs").write_text(src(value))
        git("add", "main.rs")
        git("commit", "-qm", branch)


def history(root, log, sdk, driver_name, role_files, env, *, case, producer, consumer, mode,
            aged=False, direct=False, producer_cold_mode=None):
    work = root / "cross-reader-work"
    cache = work / "cache"
    need(not cache.exists(), "history needs its own initially empty cache")
    output = work / "program"
    original_paths = {}

    def activate(role):
        for name, source in role_files[role].items():
            dest = sdk / name
            if not dest.samefile(source):
                temp = dest.with_name(dest.name + ".cross-tmp")
                os.link(source.resolve(strict=True), temp)
                os.replace(temp, dest)
            need(dest.samefile(source), "driver or matching rustdoc failed activation")
        selected = Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", "rustc"], env=env, text=True
            ).strip()
        )
        need(selected.samefile(sdk / "bin/rustc"), "wrong rustc proxy")
        original_paths[role] = {
            n: [sha(sdk / n), (sdk / n).stat().st_dev, (sdk / n).stat().st_ino]
            for n in role_files[role]
        }

    folder = log / case
    folder.mkdir()

    def visit(label, role, checkout, assertion, *, trace=False, expect=0):
        place = folder / label
        place.mkdir()
        activate(role)
        desired = "cross-" + checkout
        if subprocess.check_output(["git", "-C", work, "branch", "--show-current"], text=True).strip() != desired:
            subprocess.run(["git", "-C", work, "switch", "-q", desired], check=True)
        value = 17 if checkout == "A" else 29
        need((work / "main.rs").read_text() == src(value), "wrong committed branch contents")
        output.unlink(missing_ok=True)
        args = [
            "rustc",
            "+ohm",
            "main.rs",
            "--crate-name",
            "cross_branch_tables",
            "-Zohm-check-relink-inputs",
            "-Zohm-shared-stages",
            "-Zohm-branch-cache=yes",
            "-C",
            "incremental=" + str(cache),
            "-C",
            "codegen-units=1",
            "-Zassert-incr-state=" + assertion,
            "-o",
            output,
        ]
        if trace:
            args = [
                "strace",
                "-ff",
                "-qq",
                "-yy",
                "-s",
                "96",
                "-e",
                "trace=execve,execveat,clone,clone3,fork,vfork,mmap,openat,read,pread64,link,linkat",
                "-o",
                place / "kernel",
                *args,
            ]
        result = command(
            args, work, env | {"CARGO_MANIFEST_DIR": str(work)}, place / "compiler", expect
        )
        if expect:
            need(
                DENIAL in result.stderr
                and b"internal compiler error" not in result.stderr
                and not output.exists(),
                "missing cold-loaded rejection",
            )
            return None
        good = command([output], work, env | {"EXPECT": str(value)}, place / "right")
        wrong = command([output], work, env | {"EXPECT": str(46 - value)}, place / "wrong", 19)
        need(good.stdout == wrong.stdout == f"{value}\n".encode(), "unexpected native branch program")
        digest = sha(output)
        images = log / "elf"
        images.mkdir(exist_ok=True)
        held = images / (digest + ".gz")
        if not held.exists():
            held.write_bytes(gzip.compress(output.read_bytes(), compresslevel=1, mtime=0))
        return digest

    cold = visit("cold-A", producer, "A", "not-loaded")
    (a,) = sessions(cache)
    cold_mode = producer_cold_mode or ("packed" if producer == "E" else "raw")
    need(cold_mode in ("packed", "raw"), "unknown cold representation")
    baseline = tables(a, cold_mode, folder / "cold-A")
    first = None
    if not direct:
        first = visit("first-B", producer, "B", "loaded")
        need(len(sessions(cache)) == 2 and a in sessions(cache) and first != cold,
             "incorrect first switch")
    if aged:
        prev = sessions(cache)
        visit("producer-return-A", producer, "A", "loaded")
        (a,) = sessions(cache) - prev
        visit("producer-return-B", producer, "B", "loaded")
    need(a in sessions(cache), "producer discarded the enrolled A")
    ingress = tables(a, mode, folder)
    if not aged:
        need(
            all(ingress[n] == baseline[n] for n in NAMES),
            "the first finalized A table changed in place",
        )
    source_marker = "cross-reader-origin"
    marker = a / source_marker
    need(
        not any((session / source_marker).exists() for session in sessions(cache)),
        "ambiguous source witness",
    )
    marker_body = (case + " " + str(a) + "\n").encode()
    with marker.open("xb") as fd:
        fd.write(marker_body)
    st = marker.stat()
    before = sessions(cache)
    returned = visit("consumer-return-A", consumer, "A", "loaded", trace=True)
    (rebuilt,) = sessions(cache) - before
    now = rebuilt / source_marker
    need(
        now.is_file()
        and now.read_bytes() == marker_body
        and (now.stat().st_dev, now.stat().st_ino) == (st.st_dev, st.st_ino)
        and not a.exists(),
        "consumer used a different incremental source",
    )
    retained_marker_identity = [now.stat().st_dev, now.stat().st_ino]
    retained_marker_hash = sha(now)
    actual = kernel(
        folder / "consumer-return-A",
        folder / "consumer-return-A/kernel",
        sdk / driver_name,
        mode,
        ingress,
        rebuilt,
        marker,
    )
    if direct:
        first = visit("consumer-first-B", consumer, "B", "loaded")
        need(first != cold, "wrong independently observed B result")
    held = work / ("closed-" + case)
    cache.rename(held)
    empty = visit("consumer-empty-A", consumer, "A", "not-loaded")
    need(
        returned == empty and not any((p / source_marker).exists() for p in sessions(cache)),
        "return differs from its own independent empty",
    )
    cache.rename(work / ("empty-" + case))
    visit("empty-refuses-loaded", consumer, "A", "loaded", expect=1)
    # No source target or user cache is removed; all files are disposable within this one QA fixture.
    if cache.exists():
        cache.rename(work / ("rejected-" + case))
    proof = {
        "producer": producer,
        "consumer": consumer,
        "representation": mode,
        "cold_representation": cold_mode,
        "immediate_cold_read": direct,
        "cold_tables": baseline,
        "producer_cold": cold,
        "first_B": first,
        "first_B_compiler": consumer if direct else producer,
        "return_elf": returned,
        "own_empty_elf": empty,
        "source": str(a),
        "source_tables": ingress,
        "marker": [st.st_dev, st.st_ino],
        "returned_marker": str(now),
        "returned_marker_identity": retained_marker_identity,
        "marker_sha256": retained_marker_hash,
        "actual": actual,
        "images": original_paths,
    }
    write(folder / "qualified.json", proof)
    return proof


def checked(root, log, sdk, files, old_manifest, env):
    fixture(root / "cross-reader-work")
    directory = log / "cross-readers"
    directory.mkdir()
    names = (old_manifest["driver"], "bin/rustdoc")
    role_files = {
        "K": {n: root / "genuine-K" / n for n in names},
        "E": {n: files[Path(n)] for n in names},
    }
    fd = os.open(root / "cross-reader-work", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        mount_id = next(
            line.split()[1]
            for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines()
            if line.startswith("mnt_id:")
        )
        write(
            directory / "storage.json",
            {
                "device": os.fstat(fd).st_dev,
                "mount_id": mount_id,
                "findmnt": subprocess.check_output(
                    ["findmnt", "--json", "-T", str(root / "cross-reader-work")], text=True
                ),
            },
        )
    finally:
        os.close(fd)
    results = []
    for case, writer, reader, rep, aged, direct in (
        ("E-cold-A-to-K", "E", "K", "packed", False, True),
        ("E-first-A-to-K", "E", "K", "packed", False, False),
        ("K-first-A-to-E", "K", "E", "raw", False, False),
        ("K-packed-A-to-E", "K", "E", "packed", True, False),
    ):
        proof = history(
            root,
            directory,
            sdk,
            names[0],
            role_files,
            env,
            case=case,
            producer=writer,
            consumer=reader,
            mode=rep,
            aged=aged,
            direct=direct,
        )
        results.append([case, sha(directory / case / "qualified.json"), proof["return_elf"]])
    need(all((sdk / n).samefile(role_files["E"][n]) for n in names), "E was not restored")
    write(directory / "complete.json", results)
