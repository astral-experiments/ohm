"""Build the release's exact two binaries under different source and linker declarations."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from acquire import HERE, OUT, ROOT, need, save, sha

BINS = ("first", "second")
RUST = re.compile(r"(first|second)(?:-[0-9a-f]{16})?")
SCHEDULE = (
    ("cold17", 17),
    ("unchanged17", 17),
    ("settled17", 17),
    ("changed29", 29),
    ("unchanged29", 29),
    ("malformed", "malformed"),
    ("repair29", 29),
    ("missing", "missing"),
    ("repair37", 37),
    ("unchanged37", 37),
)
STATES = (17, 29, "malformed", "missing", 37)
BASE = HERE.parent / "smoke-test-relink.sh"
PUBLISHED = HERE / "proposed-release-relink.sh"
PROVIDERS = ROOT / "native-providers"
WORK = ROOT / "subject"


def literal(source, name):
    # Select a complete literal heredoc at the start of a command.
    matches = re.findall(
        r"(?m)^cat >" + re.escape(name) + r" <<'EOF'\n(.*?)^EOF$", source, re.DOTALL | re.MULTILINE
    )
    need(len(matches) == 1, ("ambiguous release source", name))
    return matches[0]


def sources(lane):
    need(lane in ("A", "B", "C", "U", "U-legacy"), "unknown source lane")
    original = BASE.read_text()
    prefix, native = original.split("# Both binaries call into the same native archive.", 1)
    scripts = {name: literal(prefix, name) for name in ("Cargo.toml", "engine/Cargo.toml")}
    scripts.update(
        {
            name: literal(native, name)
            for name in ("build.rs", "engine/src/lib.rs", "src/bin/first.rs", "count-links")
        }
    )
    scripts["src/bin/second.rs"] = scripts["src/bin/first.rs"]
    if lane == "B":
        needle = "echo 'pub fn register(value: usize) -> usize { value }' >engine/src/lib.rs"
        need(PUBLISHED.read_text().count(needle) == 1, "source of unmarked Rust control")
        scripts["engine/src/lib.rs"] = needle.split("'")[1] + "\n"
    if lane.startswith("U"):
        need(
            scripts["build.rs"].count("rerun-if-changed=native/libanswer.a") == 1,
            "unknown watched source",
        )
        scripts["build.rs"] = scripts["build.rs"].replace(
            "rerun-if-changed=native/libanswer.a", "rerun-if-changed=build.rs"
        )
    return scripts


def project(lane):
    WORK.mkdir()
    (WORK / "native").mkdir()
    body = sources(lane)
    for name, data in body.items():
        path = WORK / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    (WORK / "count-links").chmod(0o755)
    return {name: sha(WORK / name) for name in body}


def cmd(args, **kwargs):
    return subprocess.run(
        args, check=True, timeout=45, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    )


def provider_command(out, label, argv, *, required=True, expected=0, env=None):
    dest = out / label
    dest.mkdir()
    p = subprocess.run(argv, env=env, capture_output=True, check=False, timeout=45)
    (dest / "stdout").write_bytes(p.stdout)
    (dest / "stderr").write_bytes(p.stderr)
    save(dest / "command.json", {"argv": list(map(str, argv)), "code": p.returncode})
    if required:
        need(p.returncode == expected, (label, p.returncode, p.stderr.decode(errors="replace")[-800:]))
    return p


def make_providers():
    out = OUT / "providers"
    out.mkdir()
    PROVIDERS.mkdir()
    calibration = json.loads((OUT / "observer-probe/observed/result.json").read_bytes())
    c = Path(cmd(["xcrun", "--find", "clang"]).stdout.decode().strip())
    ar = Path(cmd(["xcrun", "--find", "ar"]).stdout.decode().strip())
    sdk = Path(cmd(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).stdout.decode().strip()).resolve(
        strict=True
    )
    lib = sdk / "usr/lib/libSystem.tbd"
    need(
        sha(c) == calibration["clang"][1]
        and str(sdk) == calibration["sdk"]
        and sha(lib) == calibration["libSystem"],
        "provider calibration must use the stock Xcode driver, SDK and libSystem already authenticated by kernel exec",
    )
    consumer = PROVIDERS / "consumer.c"
    consumer.write_text("extern int answer(void); int main(void) { return answer(); }\n")
    shutil.copyfile(consumer, out / consumer.name)
    rows = {}
    for value in (17, 29, 37):
        d = PROVIDERS / str(value)
        d.mkdir()
        dest = out / str(value)
        dest.mkdir()
        src = d / "answer.c"
        src.write_text("int answer(void) { return %d; }\n" % value)
        obj = d / "answer.o"
        archive = d / "libanswer.a"
        exe = d / "consumer"
        cc = [str(c), "-x", "c", "-c", str(src), "-o", str(obj)]
        try:
            provider_command(dest, "compile", cc)
            provider_command(
                dest, "archive", [ar, "rcs", archive, obj], env=os.environ | {"ZERO_AR_DATE": "1"}
            )
            names = provider_command(dest, "members", [ar, "-t", archive]).stdout.splitlines()
            need(
                [n for n in names if n not in (b"__.SYMDEF", b"__.SYMDEF SORTED")] == [b"answer.o"],
                "unexpected archive member",
            )
            argv = [c, consumer, archive, "-o", exe]
            if value == 17:
                # The previous runner lost stderr from this exact command. Join both link attempts to one archive.
                old = provider_command(dest, "prior-no-sdk-link", argv, required=False)
                if old.returncode == 0:
                    provider_command(dest, "prior-no-sdk-exit", [exe], expected=value)
                    shutil.copyfile(exe, dest / "prior-consumer")
                exe.unlink(missing_ok=True)
            provider_command(dest, "native-link", [c, "-isysroot", sdk, *argv[1:]])
            verdict = provider_command(dest, "native-exit", [exe], expected=value)
            rows[str(value)] = {
                "archive": sha(archive),
                "bytes": archive.stat().st_size,
                "member": sha(obj),
                "consumer": sha(exe),
                "exit": verdict.returncode,
                "cc": cc,
            }
        finally:
            for file in (src, obj, archive, exe):
                if file.is_file():
                    shutil.copyfile(file, dest / file.name)
    need(
        len({r["bytes"] for r in rows.values()}) == 1
        and len({r["archive"] for r in rows.values()}) == 3,
        "same-size three distinct native archives required",
    )
    save(
        out / "archive-check.json",
        {"rows": rows, "clang": str(c), "ar": str(ar), "sdk": str(sdk), "libSystem": sha(lib)},
    )


def put(path, state, backdate):
    before = path.stat() if path.exists() else None
    if state == "missing":
        path.unlink(missing_ok=True)
        return {"state": state, "exists": False}
    if state == "malformed":
        n = (PROVIDERS / "17/libanswer.a").stat().st_size
        data = (b"malformed native static archive\n" + b"!" * n)[:n]
    else:
        data = (PROVIDERS / str(state) / "libanswer.a").read_bytes()
    path.write_bytes(data)
    if before is not None and backdate:
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    st = path.stat()
    if before is not None and backdate:
        need(
            (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            "mutation did not retain inode, size and time",
        )
    return {
        "state": state,
        "exists": True,
        "dev": st.st_dev,
        "ino": st.st_ino,
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": sha(path),
    }


def bin_id(output, within):
    p = Path(output)
    if not p.is_absolute() or not any(p.is_relative_to(d) for d in within):
        return None
    m = RUST.fullmatch(p.name)
    return m.group(1) if m else None


def projected_errors(diagnostics, kind):
    # Accept Xcode's per-operand or library-search form, with a real failing ld required by the caller.
    text = diagnostics.lower()
    if kind == "missing":
        return "answer" in text and any(
            x in text for x in ("not found", "no such file", "could not find")
        )
    return "libanswer.a" in text and any(
        x in text
        for x in (
            "malformed",
            "unknown file type",
            "unsupported",
            "not a valid",
            "not a mach-o",
            "not an object",
            "cannot parse",
            "file too small",
            "unrecognized file format",
            "not a valid archive",
            "not mach-o",
        )
    )


def copy_sha(body):
    return hashlib.sha256(body).hexdigest()
