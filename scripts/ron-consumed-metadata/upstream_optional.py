"""Small real official compiler control for the optional binary dependency hash."""

from pathlib import Path
import hashlib, json, os, subprocess, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapped import run_child


def exercise(root, stock_home):
    root.mkdir()
    source = root / "source"
    source.mkdir()
    out = root / "output"
    out.mkdir()
    env = dict(os.environ, RUSTUP_HOME=str(stock_home), RUSTC_BOOTSTRAP="1")
    exe = (stock_home / "toolchains/ohm/bin/rustc").resolve()
    vv = subprocess.check_output(["rustc", "+ohm", "-vV"], env=env, text=True)
    assert "b940084d7eb6a299eb4bfeb8e34901bc051e7ac4" in vv
    leaf = source / "leaf.rs"
    leaf.write_text("pub const VALUE: u32 = 17;\n")
    subprocess.run(
        [
            "rustc",
            "+ohm",
            "--crate-type",
            "lib",
            "--crate-name",
            "leaf",
            "--emit=metadata",
            str(leaf),
            "--out-dir",
            str(source),
        ],
        env=env,
        check=True,
    )
    target = source / "libleaf.rmeta"
    good = target.read_bytes()
    st = target.stat()
    owner = source / "owner.rs"
    owner.write_text(
        "extern crate leaf;\nconst _: [();17]=[();leaf::VALUE as usize];\n"
        + "".join(f"pub const V{i}: u32 = leaf::VALUE ^ {i};\n" for i in range(2048))
    )
    args = [
        "rustc",
        "+ohm",
        "--edition=2021",
        "--crate-type",
        "lib",
        "--crate-name",
        "buyer",
        "--emit=dep-info,metadata",
        "--error-format=json",
        "-Zbinary-dep-depinfo",
        "-Zchecksum-hash-algorithm=blake3",
        "--extern",
        "leaf=" + str(target),
        str(owner),
        "--out-dir",
        str(out),
    ]
    rows = {}
    for mode in (
        "sham",
        "rename",
        "inplace_restore",
        "inplace",
        "independent-bad",
        "independent-repair",
    ):
        d = root / mode
        d.mkdir()
        if mode.startswith("independent"):
            tmp = d / "new-generation"
            tmp.write_bytes(good if mode.endswith("repair") else b"R" + good[1:])
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
            os.replace(tmp, target)
            p = subprocess.run(args, cwd=source, env=env, capture_output=True)
            (d / "stderr").write_bytes(p.stderr)
            v = {"rc": p.returncode}
        else:
            v = run_child(args, source, env, target, exe, out, d, mode)
        v["outputs"] = {}
        v["checksums"] = []
        for f in sorted(out.iterdir()):
            v["outputs"][f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
            if f.suffix == ".d":
                v["checksums"] = [
                    l
                    for l in f.read_text().splitlines()
                    if l.startswith("# checksum:") and l.endswith(" " + str(target))
                ]
            f.rename(d / f.name)
        v["errors"] = [
            e["code"]["code"]
            for l in (d / "stderr").read_bytes().splitlines()
            if l.startswith(b"{") and (e := json.loads(l)).get("code")
        ]
        rows[mode] = v
        fresh = d / "new-repair"
        fresh.write_bytes(good)
        os.utime(fresh, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(fresh, target)
    assert (
        rows["sham"]["rc"]
        == rows["rename"]["rc"]
        == rows["inplace_restore"]["rc"]
        == rows["independent-repair"]["rc"]
        == 0
    )
    assert rows["independent-bad"]["rc"] != 0 and rows["independent-bad"]["errors"]
    assert (
        rows["rename"]["checksums"] != rows["sham"]["checksums"]
        and rows["inplace_restore"]["checksums"] == rows["sham"]["checksums"]
    )
    return {
        "stock_rustc": vv,
        "physical_frontend": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "argv": args,
        "role_rows": rows,
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    v = exercise(root, Path(sys.argv[2]).resolve())
    (root / "result.json").write_text(json.dumps(v, sort_keys=True, indent=2) + "\n")
    print({k: (r["rc"], r["errors"][:2]) for k, r in v["role_rows"].items()})
