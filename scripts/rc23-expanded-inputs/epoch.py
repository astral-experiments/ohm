"""Reopen actual predecessor files under the installed successor's numeric format fence."""

import gzip
import os
from pathlib import Path
import shutil
import subprocess
from materialize import need, save, sha


def path_view(view, sdk, host):
    view.mkdir(exist_ok=True)
    target = view / "lib/rustlib" / host
    target.mkdir(parents=True, exist_ok=True)
    for p in (view / "bin", target / "bin", target / "lib"):
        if p.is_symlink():
            p.unlink()
        source = sdk / p.relative_to(view)
        p.symlink_to(source, target_is_directory=True)
        need(p.samefile(source), "foreign compiler search path")


def inventory(folder, bodies, epoch):
    rows = {}
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        need(not p.is_symlink(), p)
        data = p.read_bytes()
        h = sha(p)
        packet = bodies / (h + ".gz")
        if not packet.exists():
            packet.write_bytes(gzip.compress(data, mtime=0))
        need(gzip.decompress(packet.read_bytes()) == data, p)
        header = data[: 7 + data[6]].hex() if data.startswith(b"RSIC") else None
        rows[str(p.relative_to(folder))] = {"sha256": h, "bytes": len(data), "header": header}
    for name in ("dep-graph.bin", "query-cache.bin", "work-products.bin"):
        (row,) = [r for n, r in rows.items() if Path(n).name == name]
        h = bytes.fromhex(row["header"])
        need(
            h[:4] == b"RSIC" and int.from_bytes(h[4:6], "little") == epoch and h[7:] == b"rustc-perf",
            ("wrong actual header", name, h),
        )
    need(any(n.endswith(".o") for n in rows), "missing native work products")
    return rows


def migrate(root, out, host, old, new, epoch, old_epoch=10):
    root.mkdir()
    out.mkdir()
    bodies = out / "bodies"
    bodies.mkdir()
    inc, view = root / "inc", root / "visible"
    src, exe = root / "body.rs", root / "reader"
    a = 'fn main() { println!("17"); }\n'
    b = a.replace("17", "83")
    invalid = 'fn main() { let _: u32 = "wrong"; }\n'
    env = dict(
        os.environ, RUSTC_FORCE_RUSTC_VERSION="rustc-perf", RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER="rustc-perf"
    )
    rows = []

    def reset(seed=None):
        if inc.exists():
            need(inc.is_dir() and not inc.is_symlink() and inc.parent == root, inc)
            shutil.rmtree(inc)
        if seed:
            shutil.copytree(seed, inc)
            for p in seed.rglob("*"):
                if p.is_file():
                    dst = inc / p.relative_to(seed)
                    need(not dst.samefile(p) and sha(dst) == sha(p), "different restored old session")

    def visit(name, sdk, body, state, verdict, tag=b"", mismatch=False):
        phase = out / name
        phase.mkdir()
        src.write_text(body)
        exe.unlink(missing_ok=True)
        argv = [
            str(sdk / "bin/rustc"),
            "--crate-name",
            "epoch_reader",
            str(src),
            "--sysroot",
            str(view),
            "-Cstrip=symbols",
            "-Cincremental=" + str(inc),
            "-Zincremental-verify-ich",
            "-Zincremental-info",
            "-Zassert-incr-state=" + state,
            "-o",
            str(exe),
        ]
        p = subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=90)
        (phase / "stdout").write_bytes(p.stdout)
        (phase / "stderr").write_bytes(p.stderr)
        row = {
            "name": name,
            "argv": argv,
            "rustc": sha(sdk / "bin/rustc"),
            "code": p.returncode,
            "source": body,
            "stderr": sha(phase / "stderr"),
            "outcome": verdict,
        }
        save(phase / "invocation.json", row)
        err = p.stderr.decode(errors="replace")
        need("the compiler unexpectedly panicked" not in err and "internal compiler error" not in err, name)
        if mismatch:
            expected = (
                "ignoring cache artifact "
                + chr(96)
                + "dep-graph.bin"
                + chr(96)
                + ": Wrong HEADER_FORMAT_VERSION"
            )
            need(expected in err, (name, "no physical graph version refusal", err[-3000:]))
        if verdict == "loaded-refusal":
            need(
                p.returncode == 1
                and "should be successfully loaded, but it was not" in err
                and not exe.exists(),
                name,
            )
        elif verdict == "diagnostic":
            need(p.returncode == 1 and "error[E0308]" in err and not exe.exists(), name)
            row["diagnostic"] = err[err.index("error[E0308]") : err.index("\nerror: aborting due to")]
        else:
            need(p.returncode == 0 and exe.is_file(), (name, err[-3000:]))
            child = subprocess.run([str(exe)], cwd=root, capture_output=True, timeout=8)
            need(child.returncode == 0 and child.stdout == tag and not child.stderr, (name, child))
            row.update(native=sha(exe), output=child.stdout.decode())
            dst = out / (row["native"] + ".native")
            if not dst.exists():
                shutil.copy2(exe, dst)
            need(sha(dst) == row["native"], "native escrow changed")
        rows.append(row)
        return row

    path_view(view, old, host)
    visit("old-A", old, a, "not-loaded", "ok", b"17\n")
    visit("old-A-repeat", old, a, "loaded", "ok", b"17\n")
    seed = root / "old-session"
    shutil.copytree(inc, seed)
    save(out / "complete-old-session.json", inventory(seed, bodies, old_epoch))
    path_view(view, new, host)
    reset(seed)
    visit("new-loaded-refusal", new, a, "loaded", "loaded-refusal", mismatch=True)
    reset(seed)
    rejected = visit("new-invalid", new, invalid, "not-loaded", "diagnostic", mismatch=True)
    reset(seed)
    repaired = visit("new-repair-B", new, b, "not-loaded", "ok", b"83\n", True)
    save(out / "complete-new-session.json", inventory(inc, bodies, epoch))
    warm = visit("new-repeat-B", new, b, "loaded", "ok", b"83\n")
    reset()
    clean = visit("new-empty-B", new, b, "not-loaded", "ok", b"83\n")
    reset()
    error = visit("new-empty-invalid", new, invalid, "not-loaded", "diagnostic")
    need(
        repaired["native"] == warm["native"] == clean["native"]
        and rejected["diagnostic"] == error["diagnostic"],
        "clean output or source diagnostic disagreed",
    )
    save(out / "complete.json", {"old": old_epoch, "new": epoch, "phases": rows})
