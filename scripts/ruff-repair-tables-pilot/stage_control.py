"""A tiny same-directory check/build checkpoint probe, independent of ordinary Ruff freshness."""

from pathlib import Path
import gzip, hashlib, json, os, re, shutil, subprocess as sp
from protocol import need


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(n):
    return (
        "#![allow(dead_code)]\n"
        + "".join(f"pub fn f{i}(a:u32)->u32{{a.wrapping_add({i})}}\n" for i in range(500))
        + f"pub fn value()->u32{{f0(std::hint::black_box({n}))}}\n"
    ).encode()


def run(root, env, where):
    """Use ordinary Cargo to enroll compiler args, then require a true compiler stage read in the independent flank."""
    root.mkdir()
    where.mkdir()
    proj = root / "crate"
    proj.mkdir()
    for n in ("target", "build", "tmp"):
        (root / n).mkdir()
    env = env | {
        "CARGO_TARGET_DIR": str(root / "target"),
        "CARGO_BUILD_BUILD_DIR": str(root / "build"),
        "TMPDIR": str(root / "tmp"),
    }
    sp.run(["git", "init", "-qb", "a", proj], check=True)
    (proj / "Cargo.toml").write_text(
        '[workspace]\n[package]\nname="stage_witness"\nversion="0.0.0"\nedition="2024"\n[lib]\npath="lib.rs"\n'
    )
    (proj / "lib.rs").write_bytes(source(17))
    cmd = ["git", "-C", str(proj), "-c", "user.name=QA", "-c", "user.email=qa@example.invalid"]
    sp.run([*cmd, "add", "Cargo.toml", "lib.rs"], check=True)
    sp.run([*cmd, "commit", "-qm", "A"], check=True)
    sp.run([*cmd, "switch", "-qc", "b"], check=True)
    (proj / "lib.rs").write_bytes(source(29))
    sp.run([*cmd, "commit", "-qam", "B"], check=True)
    sp.run([*cmd, "switch", "-q", "a"], check=True)
    out = {}
    native = {}
    metadata = {}
    info = {}

    def cargo(label, mode="build", bad=False):
        d = where / label
        d.mkdir()
        argv = ["cargo", "+ohm", mode, "--offline", "--lib", "-j1", "--message-format=json"]
        args = [
            "strace",
            "-f",
            "-qq",
            "--seccomp-bpf",
            "-yy",
            "-s",
            "131072",
            "-e",
            "trace=execve,openat,openat2,flock,link,linkat,rename,renameat,renameat2,mmap",
            "-o",
            str(d / "source.trace"),
            *argv,
        ]
        res = sp.run(args, cwd=proj, env=env, capture_output=True, timeout=120)
        raw = (d / "source.trace").read_bytes()
        for name, blob in (("stdout", res.stdout), ("stderr", res.stderr), ("trace", raw)):
            (d / (name + ".gz")).write_bytes(gzip.compress(blob, 2, mtime=0))
        (d / "source.trace").unlink()
        rows = [json.loads(v) for v in res.stdout.splitlines()]
        need(
            res.returncode == (101 if bad else 0)
            and rows[-1] == {"reason": "build-finished", "success": not bad},
            ("tiny Cargo verdict", label, res.stderr[-850:]),
        )
        if bad:
            ee = [
                m["message"]
                for m in rows
                if m["reason"] == "compiler-message"
                and m["message"]["level"] == "error"
                and m["message"]["code"]
            ]
            need(len(ee) == 1 and ee[0]["code"]["code"] == "E0308", "wrong tiny source error")
        else:
            units = [m for m in rows if m["reason"] == "compiler-artifact"]
            need(
                len(units) == 1 and units[0]["target"]["name"] == "stage_witness", "wrong actual library unit"
            )
            (product,) = [
                Path(n) for n in units[0]["filenames"] if n.endswith(".rmeta" if mode == "check" else ".rlib")
            ]
            need(product.is_file() and product.stat().st_size > 1000, "missing tiny real Cargo product")
            if mode == "check":
                p = sp.run(
                    ["rustc", "+ohm", "-Zls=root", str(product)], env=env, cwd=proj, capture_output=True
                )
                need(
                    p.returncode == 0
                    and b"Crate info:" in p.stdout
                    and b"name stage_witness" in p.stdout
                    and not p.stderr,
                    "tiny checked metadata unreadable",
                )
                (d / "listing.gz").write_bytes(gzip.compress(p.stdout, mtime=0))
                metadata[label] = sha(product)
            else:
                client = proj / "reader.rs"
                client.write_text('fn main(){println!("{}",stage_witness::value());}\n')
                reader = root / "reader"
                sp.run(
                    [
                        "rustc",
                        "+ohm",
                        "--edition=2024",
                        str(client),
                        "--extern",
                        "stage_witness=" + str(product),
                        "-o",
                        str(reader),
                    ],
                    env=env,
                    cwd=proj,
                    check=True,
                )
                value = int(sp.check_output([reader], env=env))
                want = 17 if label == "cold-a" else 29
                need(value == want, ("bad native tiny reader", label, value, want))
                native[label] = [value, sha(reader)]
        lines = raw.decode(errors="strict").splitlines()
        reads = [
            s
            for s in lines
            if "openat(" in s
            and "O_RDONLY" in s
            and re.search(r"= \d+<", s)
            and "/incremental/" in s
            and any(n in s for n in ("dep-graph.bin", "query-cache.bin"))
        ]
        locks = [
            s
            for s in lines
            if "flock(" in s
            and "/incremental/" in s
            and ".lock>" in s
            and "LOCK_SH" in s
            and re.search(r"=\s*0$", s)
        ]
        stages = [
            s for s in reads if re.search(r"/(ohm-(build|check)-|ohm-packed-)(dep-graph|query-cache)\.bin", s)
        ]
        info[label] = {
            "fresh": None if bad else units[0]["fresh"],
            "checkpoint_opens": stages,
            "actual_graph_opens": reads,
            "shared_locks": locks,
        }
        (d / "parsed.json").write_text(json.dumps(info[label], sort_keys=True) + "\n")
        return info[label]

    cargo("cold-a")
    sp.run([*cmd, "switch", "-q", "b"], check=True)
    cargo("first-b")
    (proj / "lib.rs").write_bytes(source(29) + b"const _:u8=false;\n")
    cargo("invalid", bad=True)
    cargo("invalid-repeat", bad=True)
    (proj / "lib.rs").write_bytes(source(29))
    cargo("repair")
    cargo("check", "check")
    cargo("build-after-check")
    # An actual subsequent source timestamp change forces both frontends in their own stage;
    # keeping the byte-identical public behavior preserves independent native output parity.
    (proj / "lib.rs").write_bytes(source(29) + b"\n")
    cargo("check-source-edit", "check")
    (proj / "lib.rs").write_bytes(source(29) + b"\n\n")
    cargo("build-source-edit")
    # For the stage flavor that is not Cargo-fresh both graph+query writes are mandatory observations.
    for label in ("check", "check-source-edit", "build-source-edit"):
        r = info[label]
        # A first check after build can legitimately fall through to canonical tables.
        # The next genuine link-producing compiler with a previous check must read an actual build checkpoint.
        prefix = "ohm-build-" if label == "build-source-edit" else ""
        need(
            r["fresh"] is False
            and r["shared_locks"]
            and all(
                any("-working/" + prefix + suffix + '"' in s for s in r["actual_graph_opens"])
                for suffix in ("dep-graph.bin", "query-cache.bin")
            ),
            ("missing actual shared prior session and opened staged tables", label, r),
        )
    for path in (root / "target", root / "build"):
        need(path.is_dir() and not path.is_symlink() and path.parent == root, "wrong fixture cleanup")
        shutil.rmtree(path)
    # References use identical source bytes for each enrolled stage and exactly the same canonical output paths.
    (proj / "lib.rs").write_bytes(source(29))
    cargo("empty-check", "check")
    for path in (root / "target", root / "build"):
        if path.exists():
            shutil.rmtree(path)
    cargo("empty-build")
    need(
        metadata["check"] == metadata["empty-check"]
        and all(native[p] == native["empty-build"] for p in ("repair", "build-after-check")),
        "tiny same-source clean parity",
    )
    report = {
        "scope": "ordinary tiny builds plus independent physically forced stages; no whole-Ruff checkpoint claim from cached Cargo",
        "native": native,
        "metadata": metadata,
        "visits": info,
    }
    (where / "complete.json").write_text(json.dumps(report, sort_keys=True) + "\n")
    return report
