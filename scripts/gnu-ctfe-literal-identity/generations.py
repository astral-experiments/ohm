"""Private incremental-generation and public rlib interoperability controls at one compiler stamp.

Pass --candidate when that driver has been compiled. With E alone, mark an owned
copy of the old query cache as generation 11 and corrupt its trailer; the original
must refuse it before decoding, still produce the true binary, and load its next cache.
"""

import argparse, gzip, hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROXY = Path(shutil.which("rustup")).parent / "rustc"
STAMP = "ctfe-literal-identical-incremental-stamp"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", required=True, type=Path)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    r = a.out
    r.mkdir()
    old = a.old.resolve(strict=True)
    roles = {"E": (old, 8)}
    if a.candidate:
        roles["C"] = (a.candidate.resolve(strict=True), 11)
    assert shutil.disk_usage(r).free > 4 * (1 << 30) + 75 * (1 << 20)
    receipt = {"runs": [], "sdk": {}, "same_stamp": STAMP, "emulated_new_header": not a.candidate}
    with tempfile.TemporaryDirectory(dir=r, prefix="isolated-") as temp:
        t = Path(temp)
        rustup = t / "rustup"
        (rustup / "toolchains").mkdir(parents=True)
        alias = rustup / "toolchains/ohm"
        w = t / "project"
        w.mkdir()
        (t / "tmp").mkdir()
        (w / "main.rs").write_text('fn main() { println!("17"); }\n')
        env = {
            "HOME": str(t),
            "RUSTUP_HOME": str(rustup),
            "RUSTUP_AUTO_INSTALL": "0",
            "RUSTC_BOOTSTRAP": "1",
            "RUSTC_FORCE_RUSTC_VERSION": STAMP,
            "PATH": str(Path(shutil.which("rustup")).parent) + ":/usr/local/bin:/usr/bin:/bin",
            "LC_ALL": "C",
            "TMPDIR": str(t / "tmp"),
        }

        def ps(role):
            sdk, version = roles[role]
            if not alias.is_symlink() or alias.resolve() != sdk:
                alias.unlink(missing_ok=True)
                alias.symlink_to(sdk)
            e = dict(env, LD_LIBRARY_PATH=str(sdk / "lib"))
            (driver,) = (sdk / "lib").glob("librustc_driver-*.so")
            if role not in receipt["sdk"]:
                receipt["sdk"][role] = {
                    "driver": sha(driver),
                    "rustc": sha(sdk / "bin/rustc"),
                    "version": subprocess.check_output([PROXY, "+ohm", "-vV"], env=e, text=True),
                    "sysroot": str(sdk),
                    "generation": version,
                }
                assert Path(
                    subprocess.check_output([PROXY, "+ohm", "--print", "sysroot"], env=e, text=True).strip()
                ).samefile(sdk)
                if role == "E":
                    assert (
                        receipt["sdk"][role]["driver"]
                        == "f20d40da3f9365b0d3544ad76136e8c1036a6d1a5ecb39281e972f782fa33ae6"
                    )
            return e, version

        def run(role, cmd, name, expected=0):
            e, ver = ps(role)
            x = subprocess.run(cmd, env=e, cwd=w, capture_output=True, timeout=60)
            receipt["runs"].append(
                dict(
                    role=role,
                    name=name,
                    argv=list(map(str, cmd)),
                    code=x.returncode,
                    stdout=x.stdout.decode(errors="replace"),
                    stderr=x.stderr.decode(errors="replace"),
                )
            )
            (r / "partial.json").write_text(json.dumps(receipt) + "\n")
            assert x.returncode == expected, (name, x.stderr[-1000:])
            return x.stdout

        def cc(role, phase, assertion):
            opts = [
                "--crate-name",
                "identity",
                "-Cincremental=" + str(w / "inc"),
                "-Zassert-incr-state=" + assertion,
                "main.rs",
                "-o",
                str(w / "main"),
            ]
            run(role, [PROXY, "+ohm", *opts], phase)
            v = run(role, [w / "main"], phase + "-native")
            assert v == b"17\n"
            hdr = []
            for f in (w / "inc").rglob("query-cache.bin"):
                b = f.read_bytes()
                assert b.startswith(b"RSIC") and b[7 : 7 + b[6]] == STAMP.encode(), (f, b[:80])
                hdr.append((str(f.relative_to(w)), int.from_bytes(b[4:6], "little"), sha(f)))
            assert {i for _, i, _ in hdr} == {roles[role][1]}, hdr
            receipt.setdefault("written_headers", {})[phase] = hdr

        cc("E", "old-empty", "not-loaded")
        cc("E", "old-warm", "loaded")
        if a.candidate:
            cc("C", "old-to-new", "not-loaded")
            cc("C", "new-warm", "loaded")
            cc("E", "new-to-old", "not-loaded")
            cc("E", "old-warm-again", "loaded")
            (w / "foreign.rs").write_text(
                'pub static A:u8=17; pub static B:u8=17; pub const REFS:[&u8;3]=[&A,&A,&B]; #[inline] pub fn word()->&\\x27static str{"word"}\n'.replace(
                    "\\x27", "'"
                )
            )
            (w / "client.rs").write_text(
                'extern crate foreign; fn main(){let [a,b,c]=foreign::REFS; assert!(std::ptr::eq(a,b)&&!std::ptr::eq(a,c)); println!("{} {}",foreign::word(),*a);}\n'
            )
            for writer, reader in [("E", "C"), ("C", "E")]:
                run(
                    writer,
                    [PROXY, "+ohm", "--crate-type=rlib", "--crate-name", "foreign", "foreign.rs"],
                    writer + "-write-rlib",
                )
                run(
                    reader,
                    [PROXY, "+ohm", "client.rs", "--extern", "foreign=libforeign.rlib", "-o", "client"],
                    reader + "-read-rlib",
                )
                assert run(reader, [w / "client"], reader + "-native-client") == b"word 17\n"
        else:
            for f in (w / "inc").rglob("query-cache.bin"):
                b = bytearray(f.read_bytes())
                b[4:6] = (11).to_bytes(2, "little")
                b[-20:] = b"poison-before-decode"
                f.unlink()
                f.write_bytes(b)
            cc("E", "old-refuses-11-poisoned", "not-loaded")
            cc("E", "old-own-repaired", "loaded")
    (r / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(len(receipt["runs"]), receipt["sdk"], r)


if __name__ == "__main__":
    main()
