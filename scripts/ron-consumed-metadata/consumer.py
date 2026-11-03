"""Link and execute a real Ron reader against each produced archive at fixed visible paths."""

import hashlib, json, os, shutil, subprocess
from pathlib import Path

SOURCE = """fn main() {
    let value: Vec<u16> = ron::from_str("[8,13,21]").unwrap();
    assert_eq!(value, [8,13,21]);
    let text = ron::ser::to_string(&value).unwrap();
    let back: Vec<u16> = ron::from_str(&text).unwrap();
    assert_eq!(back, value);
    let bad = ron::from_str::<Vec<u16>>("[8, \\"bad\\"]").unwrap_err();
    assert!(bad.span.start.line > 0);
    println!("valid={text} roundtrip={} malformed={}:{}",back.len(),bad.span.start.line,bad.span.start.col);
}
"""


def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(root, env, search, inputs):
    root.mkdir()
    source = root / "reader.rs"
    src = SOURCE
    source.write_text(src)
    fixed = root / "input"
    fixed.mkdir()
    records = {}
    for name, at in inputs.items():
        where = root / name
        where.mkdir()
        members = {}
        for ext in ("rlib", "rmeta"):
            old = next(at.glob("libron-*." + ext))
            dest = fixed / old.name
            shutil.copyfile(old, dest)
            members[ext] = digest(dest)
        native = root / "reader"
        archive = next(fixed.glob("*.rlib"))
        metadata = next(fixed.glob("*.rmeta"))
        args = [
            "rustc",
            "+ohm",
            "--edition=2021",
            "--crate-name",
            "ron_consumer",
            str(source),
            "--extern",
            "ron=" + str(metadata),
            "--extern",
            "ron=" + str(archive),
            "-Cdebuginfo=0",
            "--error-format=json",
            *search,
            "-o",
            str(native),
        ]
        with (where / "compile.stderr").open("xb") as se:
            s = subprocess.run(
                args, env=env, cwd=root, stdout=subprocess.PIPE, stderr=se
            )
        assert s.returncode == 0, (name, (where / "compile.stderr").read_text()[:1600])
        r = subprocess.run([str(native)], capture_output=True, check=True)
        assert (
            r.stdout.startswith(b"valid=[8,13,21] roundtrip=3 malformed=1:")
            and r.stderr == b""
        )
        records[name] = {
            "rlib": members["rlib"],
            "rmeta": members["rmeta"],
            "ELF": digest(native),
            "size": native.stat().st_size,
            "stdout": r.stdout.decode(),
        }
        native.rename(where / "reader")
    source.write_text(
        src.replace(
            "let value: Vec<u16> =",
            'let _: String = ron::from_str::<Vec<u16>>("[1]").unwrap();\n    let value: Vec<u16> =',
        )
    )
    invalid = subprocess.run(args, cwd=root, env=env, capture_output=True)
    (root / "invalid.stderr").write_bytes(invalid.stderr)
    assert (
        invalid.returncode != 0 and b'"E0308"' in invalid.stderr and not native.exists()
    )
    source.write_text(src)
    repair = subprocess.run(args, cwd=root, env=env, capture_output=True)
    assert repair.returncode == 0
    assert digest(native) == records[name]["ELF"]
    return {
        "physical_artifacts": records,
        "invalid_E0308": True,
        "repair_elf": digest(native),
        "literal_last_argv": args,
    }
