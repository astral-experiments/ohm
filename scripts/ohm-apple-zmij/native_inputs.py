"""A real archive is replaced and broken after a successful native link. The ordinary declared input must still matter."""

import os
import shutil
from pathlib import Path

from measure import capture, native_rows, select, typed
from study import env_for, need, run, save, sha


def run_archive_check(root, role, trace, label=None):
    work = root / "native-input-work"
    work.mkdir(exist_ok=True)
    sdk = select(root, role)
    env = env_for(work, sdk)
    src = work / "crate"
    src.mkdir(exist_ok=True)
    (src / "src").mkdir(exist_ok=True)
    (src / "Cargo.toml").write_text(
        '[package]\nname="qa_native_input"\nversion="0.1.0"\nedition="2024"\n[workspace]\n'
    )
    (src / "build.rs").write_text(
        'fn main(){let d=std::env::var("CARGO_MANIFEST_DIR").unwrap();'
        'println!("cargo:rerun-if-changed=native/libqa_answer.a");println!("cargo:rustc-link-search=native={d}/native");'
        'println!("cargo:rustc-link-lib=static=qa_answer");}\n'
    )
    (src / "src/main.rs").write_text(
        'unsafe extern "C" {fn qa_answer()->i32;} fn main(){println!("{}",unsafe{qa_answer()});}\n'
    )
    native = src / "native"
    native.mkdir(exist_ok=True)
    command = ["cargo", "+ohm", "build", "--locked", "--offline", "--message-format=json"]
    archive = native / "libqa_answer.a"
    refs = {}
    for val in (17, 29):
        (native / "provider.c").write_text(f"int qa_answer(void){{return {val};}}\n")
        run(["xcrun", "clang", "-O1", "-c", str(native / "provider.c"), "-o", str(native / "provider.o")])
        if archive.exists():
            archive.unlink()
        run(["xcrun", "ar", "crs", str(archive), str(native / "provider.o")])
        refs[val] = archive.read_bytes()
    need(refs[17] != refs[29], "real native provider outputs must differ")
    run(["cargo", "+ohm", "generate-lockfile", "--offline"], cwd=src, env=env)
    history = {}
    for phase, body, want in (
        ("initial", refs[17], 17),
        ("unchanged", None, 17),
        ("replace", refs[29], 29),
        ("malformed", b"not a native archive\n", None),
        ("missing", b"", None),
        ("repair", refs[29], 29),
        ("empty-reference", refs[29], 29),
    ):
        if phase == "empty-reference":
            for k in ("target", "shared"):
                p = work / k
                if p.exists():
                    shutil.rmtree(p)
        if body is not None:
            if archive.exists():
                archive.unlink()
            if body:
                archive.write_bytes(body)
        out = root / "receipts/native-input" / (label or role) / phase
        status, stdout, stderr, jobs, streams = capture(command, src, env, out, trace)
        arts, _, _, _ = typed(stdout, want is not None)
        roster = native_rows(jobs, sdk) if jobs is not None else None
        need(
            (roster is None or roster["cargo"] in (None, 1)) and status == (0 if want else 101),
            "wrong real Cargo verdict",
        )
        row = {
            "cargo_exit": status,
            "archive": sha(archive) if archive.exists() else None,
            "native": roster,
            "streams": streams,
        }
        if want is not None:
            (exe,) = [
                Path(r["executable"])
                for r in arts
                if r.get("executable") and r["target"]["name"] == "qa_native_input"
            ]
            value = run([str(exe)]).strip()
            need(value == str(want).encode(), "stale native value")
            row.update(value=want, executable=sha(exe))
            if (
                phase in ("initial", "replace", "repair", "empty-reference")
                and roster
                and roster["linkers"] is not None
            ):
                need(any(l["stock"] for l in roster["linkers"]), "expected actual Apple native relink")
        else:
            need(b"qa_answer" in stdout + stderr, "unrelated native rejection")
        save(out / "verified.json", row)
        history[phase] = row
    need(
        history["repair"]["executable"] == history["empty-reference"]["executable"],
        "repaired native Mach-O differs from clean",
    )
    save(root / "receipts/native-input" / (label or role) / "terminal.json", history)
    for k in ("target", "shared", "cargo-home", "crate"):
        p = work / k
        if p.exists():
            shutil.rmtree(p)
