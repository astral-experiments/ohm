"""Real Cargo-owned executable must honor an in-place, backdated GNU static native provider."""

from pathlib import Path
import json
import os
import shutil
import subprocess
from binding import need, sha
from donor_open import Watch, OPEN
import events as cold_events
from native_outputs import run, write, store

COMMAND = ["cargo", "+ohm", "build", "--locked", "--offline", "-j2", "--message-format=json"]
BODY = """core::arch::global_asm!(".pushsection .rodata", ".byte 55", ".popsection");
unsafe extern "C" { fn same_revision_provider_value() -> i32; }
fn main() { println!("{} {}", unsafe { same_revision_provider_value() }, std::hint::black_box(BRANCH)); }
"""


def paths_empty(place, tag):
    p = place / tag
    if p.exists():
        need(
            p.is_dir()
            and not p.is_symlink()
            and not p.is_mount()
            and p.resolve() == p
            and p.stat().st_dev == place.stat().st_dev
            and (place / ".owned").read_text() == str(place),
            "unowned target",
        )
        shutil.rmtree(p)
    p.mkdir()


def linked_families(raw, events, wild):
    """Attribute a fork-only helper only when its validated lifetime has no intervening exec."""
    parents = {}
    pids = {}
    installed = {}
    for line in raw.splitlines():
        words = line.split(b"\t")
        if words[0] == b"R":
            pids[int(words[1])] = int(words[2])
        if words[0] == b"N":
            g, p, kind, c, child = map(int, words[1:])
            parents[c] = g
            pids[c] = child
    for im in events:
        installed.setdefault(im["lifetime"], []).append(im)
    roots = {e["lifetime"]: e for e in wild}
    result = {}
    for gen, pid in pids.items():
        path = gen
        while path not in roots and path not in installed and path in parents:
            path = parents[path]
        if path in roots:
            need(pid not in result, "reused ambiguous linker PID")
            result[pid] = roots[path]["pid"]
    return result


def exercise(b, env, role, output, reader):
    place = b.ROOT / "same-revision-native-provider"
    need(place.resolve() == place and not place.exists(), "previous private provider state")
    place.mkdir()
    (place / ".owned").write_text(str(place))
    output.mkdir()
    src = place / "source"
    src.mkdir()
    (src / "src").mkdir()
    lib = place / "native"
    lib.mkdir()
    native = lib / "libsame_revision.a"
    cas = output / "bodies"
    cas.mkdir()
    active = env | {
        "CARGO_BUILD_BUILD_DIR": str(place / "build"),
        "CARGO_TARGET_DIR": str(place / "target"),
        "GIT_AUTHOR_NAME": "Ohm QA",
        "GIT_AUTHOR_EMAIL": "qa@example.invalid",
        "GIT_COMMITTER_NAME": "Ohm QA",
        "GIT_COMMITTER_EMAIL": "qa@example.invalid",
        "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
    }

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "commit.gpgsign=false", "-C", src, *args], env=active, text=True
        ).strip()

    git("init", "-q", "--template=", "-b", "old")
    (src / "Cargo.toml").write_text(
        '[package]\nname="revision_probe"\nversion="0.0.0"\nedition="2024"\n[workspace]\n'
    )
    (src / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "revision_probe"\nversion = "0.0.0"\n'
    )
    (src / "build.rs").write_text(
        'fn main(){let n=std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("native"); println!("cargo::rerun-if-changed={}",n.join("libsame_revision.a").display()); println!("cargo::rustc-link-search=native={}",n.display()); println!("cargo::rustc-link-lib=static=same_revision");}\n'
    )
    main = src / "src/main.rs"
    main.write_text(BODY.replace("BRANCH", "1"))
    git("add", ".")
    git("commit", "-qm", "A")
    git("switch", "-qc", "recent")
    main.write_text(BODY.replace("BRANCH", "2"))
    git("commit", "-qam", "B")
    git("branch", "y")
    git("switch", "-q", "y")
    payload = {}
    for value in (17, 29, 37):
        (lib / "value.c").write_text(f"int same_revision_provider_value(void){{return {value};}}\n")
        for arg in (
            ["cc", "-O2", "-c", "value.c", "-o", "value.o"],
            ["ar", "crsD", "next.a", "value.o"],
        ):
            subprocess.run(arg, cwd=lib, env=active, check=True, capture_output=True)
        payload[value] = (lib / "next.a").read_bytes()
        (lib / "next.a").unlink()
    need(
        len({len(s) for s in payload.values()}) == 1 and len(set(payload.values())) == 3,
        "real archive variants unsupported",
    )
    payload["bad"] = (b"not_an_object_or_a_linker_script " * (len(payload[17]) // 32 + 2))[
        : len(payload[17])
    ]
    native.write_bytes(payload[17])
    stamp = (1_600_000_000_000_000_000,) * 2
    os.utime(native, ns=stamp)
    baseline = native.stat()

    def replace(value):
        with native.open("r+b") as f:
            f.write(payload[value])
            f.flush()
            os.fsync(f.fileno())
        os.utime(native, ns=stamp)
        s = native.stat()
        need(
            (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
            == (baseline.st_dev, baseline.st_ino, baseline.st_size, baseline.st_mtime_ns)
            and native.read_bytes() == payload[value],
            "provider placement or bytes changed incorrectly",
        )
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, sha(native)]

    actual = {}

    def phase(tag, value, branch, changed):
        dest = output / tag
        dest.mkdir()
        physical = replace(value)
        mark = Watch([native])
        try:
            cold = tag == "initial-Y" or tag.startswith("empty-")
            observer = b.ROOT / ("event-only-cold" if cold else "donor-observer/observe")
            raw = dest / "kernel.tsv"
            r = run(
                [observer, raw, "--", *COMMAND],
                active,
                src,
                dest,
                "cargo",
                101 if value == "bad" else 0,
            )
        finally:
            write(dest / "file-opens.json", mark.close())
        log = raw.read_bytes()
        ev = (
            cold_events.reopen(log, r.returncode)
            if cold
            else reader.parse(log, expected_code=r.returncode, expected_schema=3)
        )["execs"]
        wild = b.SDK / b.WILD
        w = wild.stat()
        native_link = [
            e
            for e in ev
            if (e["image"]["dev"], e["image"]["ino"], e["image"]["sha256"])
            == (w.st_dev, w.st_ino, b.WILD_ELF)
        ]
        ids = linked_families(log, ev, native_link)
        opens = json.loads((dest / "file-opens.json").read_bytes())
        selected = {ids[e["pid"]] for e in opens["events"] if e["mask"] & OPEN and e["pid"] in ids}
        emitted = [m for m in map(json.loads, r.stdout.splitlines())]
        need(
            emitted[-1] == {"reason": "build-finished", "success": value != "bad"},
            "wrong Cargo native verdict",
        )
        actual_outputs = []
        cmd_output = None
        if value == "bad":
            need(
                selected and b"link" in (r.stdout + r.stderr).lower(),
                "malformed did not reach a genuine GNU linker",
            )
            elf = None
            stdout = None
        else:
            (exe,) = [Path(m["executable"]) for m in emitted if m.get("executable")]
            child = run([exe], active, src, dest, "runtime")
            need(
                child.stdout == f"{value} {branch}\n".encode() and not child.stderr,
                "stale native output",
            )
            elf = store(cas, exe.read_bytes())
            stdout = child.stdout.decode()
            s = exe.stat()
            cmd_output = [str(exe), s.st_dev, s.st_ino, *elf]
            if changed:
                need(selected, "did not observe stock Wild physically open same-inode input")
                matches = []
                for im in native_link:
                    a = im["argv"]
                    if im["pid"] in selected and "-o" in a:
                        p = Path(a[a.index("-o") + 1])
                        if p.is_file() and (p.samefile(exe) or sha(p) == elf[1]):
                            s = p.stat()
                            matches.append(
                                [im["pid"], str(p), s.st_dev, s.st_ino, s.st_size, sha(p)]
                            )
                need(matches, "actual opening linker did not produce this program")
                actual_outputs = matches
        row = dict(
            source=git("rev-parse", "HEAD"),
            branch=git("symbolic-ref", "--short", "HEAD"),
            provider=physical,
            observed_linkers=sorted(selected),
            links=native_link,
            published_outputs=actual_outputs,
            cargo_executable=cmd_output,
            exit=r.returncode,
            elf=elf,
            stdout=stdout,
            archive=store(cas, payload[value]),
        )
        write(dest / "result.json", row)
        actual[tag] = row

    phase("initial-Y", 17, 2, True)
    git("switch", "-q", "old")
    phase("historical-X", 17, 1, True)
    git("merge", "--ff-only", "--quiet", "y")
    phase("fast-forward-X", 17, 2, True)
    git("switch", "-q", "y")
    phase("unchanged-input", 17, 2, False)
    phase("same-inode-29", 29, 2, True)
    phase("malformed", "bad", 2, True)
    phase("repair-37", 37, 2, True)
    phase("repeat-37", 37, 2, False)
    for value, name in ((29, "empty-29"), ("bad", "empty-bad"), (37, "empty-37")):
        for q in ("build", "target"):
            paths_empty(place, q)
        phase(name, value, 2, True)
    for a, z in (
        ("same-inode-29", "empty-29"),
        ("malformed", "empty-bad"),
        ("repair-37", "empty-37"),
        ("repeat-37", "empty-37"),
    ):
        need(
            [actual[a][k] for k in ("elf", "exit", "stdout", "provider")]
            == [actual[z][k] for k in ("elf", "exit", "stdout", "provider")],
            "independent native control disagreed",
        )
    write(
        output / "qualified.json",
        {
            "role": role,
            "initial": actual["initial-Y"]["elf"],
            "terminal": {k: [v["exit"], v["stdout"], v["elf"]] for k, v in actual.items()},
        },
    )
    need(
        place.resolve() == place
        and place.parent == b.ROOT
        and not place.is_mount()
        and (place / ".owned").read_text() == str(place),
        "foreign ephemeral provider area",
    )
    shutil.rmtree(place)
