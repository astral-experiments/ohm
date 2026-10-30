"""A real archive is replaced and broken after a successful native link. The ordinary declared input must still matter."""

import os
import shutil
from pathlib import Path

from measure import capture, native_rows, select, typed
from study import MISSING, compress_bytes, env_for, need, run, save, sha


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
        'println!("cargo:rerun-if-changed=native/libqa_answer.a");println!("cargo:rustc-link-search=native={d}/native");}\n'
    )
    (src / "src/lib.rs").write_text(
        '#[link(name="qa_answer", kind="static")] unsafe extern "C" {fn qa_answer()->i32;}\n'
        '#[target_feature(enable="crc")] unsafe fn crc(mut a:u32,b:u32)->u32 {'
        'unsafe {core::arch::asm!("crc32w {a:w}, {a:w}, {b:w}",a=inout(reg)a,b=in(reg)b)}; a}\n'
        'pub fn answer()->i32 {assert!(std::arch::is_aarch64_feature_detected!("crc"));'
        'unsafe { assert_eq!(crc(0,0),0); qa_answer() }}\n'
    )
    (src / "src/main.rs").write_text('fn main(){println!("{}",qa_native_input::answer());}\n')
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
    prior = {}
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
            from cgu_inputs import witness
            from zlib_study import keep
            image = exe.read_bytes()
            keep(root, "bundled-programs", image)
            row.update(value=want, executable=sha(exe))
            final = [l["argv"] for l in roster["linkers"] if l["stock"] and any(
                a == "-o" and Path(b).name == "qa_native_input" for a,b in zip(l["argv"],l["argv"][1:]))]
            if final:
                argv, = final
                output, = [b for a,b in zip(argv,argv[1:]) if a == "-o"]
                proof = witness(root, out, image, output, linker=argv)
                prior[row["executable"]] = proof
            else:
                need(phase == "unchanged" and row["executable"] in prior, "fresh native input test without original linker")
                proof = prior[row["executable"]]
            row["cgu"] = {k: proof[k] for k in ("output", "raw", "same_path_image", "modules")}
            lib, = [r for r in arts if r["target"]["name"] == "qa_native_input" and r["target"]["kind"] == ["lib"]]
            archive_path, = [Path(p) for p in lib["filenames"] if p.endswith(".rlib")]
            dep = bundled_depinfo(work, archive_path)
            body = dep.read_bytes()
            need(b"src/lib.rs" in body and MISSING in body, "bundled archive lost its conservative dep-info marker")
            row["bundled_dep_sha256"] = compress_bytes(out/"bundled-library.dep.gz", body)
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
    from cgu_inputs import agrees
    need(
        agrees(history["repair"]["cgu"], history["empty-reference"]["cgu"]),
        "repaired native Mach-O differs from clean",
    )
    save(root / "receipts/native-input" / (label or role) / "terminal.json", history)
    for k in ("target", "shared", "cargo-home", "crate"):
        p = work / k
        if p.exists():
            shutil.rmtree(p)


def bundled_depinfo(work, returned):
    """Find the internal rlib underlying Cargo's public, sometimes unhashed output."""
    hits = {}
    for folder in ("target", "shared"):
        for member in (work/folder).rglob("libqa_native_input-*.rlib"):
            if member.samefile(returned) or (member.stat().st_size == returned.stat().st_size and sha(member) == sha(returned)):
                dep = member.with_name(member.stem.removeprefix("lib") + ".d")
                if dep.is_file():
                    hits[(dep.stat().st_dev, dep.stat().st_ino)] = dep
    result, = hits.values()
    return result
