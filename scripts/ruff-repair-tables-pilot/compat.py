"""Exercise an authenticated writer and the original #301 on its real repaired cache, both with and without retention."""

import argparse, gzip, hashlib, json, os, re, shutil, subprocess as sp, sys, zlib
from pathlib import Path

P = "393b4b05a4bfa3f531a36023846f86236a6b71a9"
R = "7c0c305743727cb08e3c1de61183c9cb953d3f33"


def check(v, name):
    if not v:
        raise ValueError(name)


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save(p, v):
    p.write_text(json.dumps(v, sort_keys=True, indent=2) + "\n")


def gz(p, raw):
    p.write_bytes(gzip.compress(raw, compresslevel=5, mtime=0))


def source(value):
    prefix = "#![allow(dead_code)]\n" + "".join(
        f"pub fn f{i}(x:u32)->u32{{x.wrapping_add({i})}}\n" for i in range(384)
    )
    return (
        prefix
        + f"static DATA:[u8;32768]=[{value};32768];\n"
        + (
            "fn main(){let _:u8=false;}"
            if value == "false"
            else 'fn main(){println!("{}",f0(std::hint::black_box(&DATA)[0].into()));}'
        )
        + "\n"
    ).encode()


def validated(row, commit):
    check(row["source"] == commit, "unregistered source")
    sdk = Path(row["sdk"]).resolve()
    m = row["members"]
    check(
        len(m) >= 80 and all((sdk / p).is_file() and sha(sdk / p) == v for p, v in m.items()),
        "entire independent SDK",
    )
    (driver,) = [k for k in m if "librustc_driver-" in k]
    return sdk, driver, m[driver]


def fixture(root, subjects, control):
    check(root.is_dir() and not list(root.iterdir()), "separately empty private subdirectory")
    kits = {"P": validated(subjects["P"], P)}
    if not control:
        kits["R"] = validated(subjects["R"], R)
        check(kits["P"][2] != kits["R"][2], "actual new driver")
    writer = "P" if control else "R"
    for r, (sdk, *_) in kits.items():
        a = root / r / "toolchains"
        a.mkdir(parents=True)
        (a / "ohm").symlink_to(sdk)
    work = root / "project"
    work.mkdir()
    f = work / "main.rs"
    out = root / "raw"
    out.mkdir()
    refs = {}
    records = {}
    for b in ("a", "b"):
        if b == "a":
            sp.run(["git", "init", "-q", "-b", "a"], cwd=work, check=True)
        else:
            sp.run(["git", "switch", "-qc", "b"], cwd=work, check=True)
        f.write_bytes(source("17" if b == "a" else "29"))
        sp.run(["git", "add", "main.rs"], cwd=work, check=True)
        sp.run(
            [
                "git",
                "-c",
                "user.name=Ohm QA",
                "-c",
                "user.email=charlie.r.marsh@gmail.com",
                "commit",
                "-qm",
                b,
            ],
            cwd=work,
            check=True,
        )

    def run(label, role, branch, mode, kind="ok", trace=None):
        d = out / label
        d.mkdir()
        sp.run(["git", "restore", "main.rs"], cwd=work, check=True)
        sp.run(["git", "switch", "-q", branch], cwd=work, check=True)
        if kind == "bad":
            f.write_bytes(source("29").replace(b"fn main(){", b"fn main(){let _:u8=false;"))
        if kind == "edit":
            f.write_bytes(source("83"))
        sdk, rel, physical = kits[role]
        proxy = Path(shutil.which("rustup")).parent
        env = dict(
            PATH=str(proxy) + ":/usr/local/bin:/usr/bin:/bin",
            HOME=str(root / "home"),
            RUSTUP_HOME=str(root / role),
            RUSTUP_AUTO_INSTALL="0",
            LD_LIBRARY_PATH=str(sdk / "lib"),
            CARGO_MANIFEST_DIR=str(work),
            LC_ALL="C",
            TMPDIR=str(root / "tmp"),
        )
        for k in ("HOME", "TMPDIR"):
            Path(env[k]).mkdir(exist_ok=True)
        cmd = [
            str(proxy / "rustc"),
            "+ohm",
            "main.rs",
            "--edition=2024",
            "--crate-name",
            "retained_build_witness",
            "-Zohm-check-relink-inputs",
            "-Zohm-shared-stages",
            "-C",
            "incremental=cache",
            "-Ccodegen-units=1",
            "-o",
            "program",
        ]
        if mode == "on":
            cmd.append("-Zohm-branch-cache=yes")
        prefix = (
            [
                "strace",
                "-f",
                "-qq",
                "-s",
                "8192",
                "-e",
                "trace=openat,linkat,execve,mmap",
                "-yy",
                "-o",
                str(d / "original.strace"),
            ]
            if trace is not None
            else []
        )
        q = sp.run([*prefix, *cmd], env=env, cwd=work, capture_output=True)
        gz(d / "stdout.gz", q.stdout)
        gz(d / "stderr.gz", q.stderr)
        data = {
            "argv": cmd,
            "status": q.returncode,
            "tree": sp.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=work, text=True).strip(),
            "source": sha(f),
            "role": role,
            "driver": physical,
            "option": mode,
        }
        if kind == "bad":
            check(q.returncode == 1 and q.stderr.count(b"error[E0308]") == 1, "exact typed error")
        else:
            check(q.returncode == 0, q.stderr.decode())
            val = sp.check_output([work / "program"], env=env).decode().strip()
            expected = "83" if kind == "edit" else "17" if branch == "a" else "29"
            check(val == expected, "native value")
            body = sha(work / "program")
            check(refs.setdefault((role, expected), body) == body, "same-role clean native ELF")
            data.update(value=val, elf=body)
        if trace is not None:
            raw = (d / "original.strace").read_text()
            hits = {}
            check(
                any("mmap(" in l and rel in l and "PROT_EXEC" in l for l in raw.splitlines()),
                "actual executable mapped driver",
            )
            for name, old in trace.items():
                short = os.path.relpath(old, work)
                opened = [
                    line
                    for line in raw.splitlines()
                    if "openat(" in line
                    and ('"' + short + '"' in line or '"' + str(old) + '"' in line)
                    and "O_RDONLY" in line
                    and re.search(r" = [0-9]+<", line)
                ]
                linked = [
                    line
                    for line in raw.splitlines()
                    if "linkat(" in line
                    and re.search(r"-working/ohm-build-" + name + r'\.bin", 0\) = 0', line)
                ]
                check(
                    opened and linked,
                    ("positive old receiver read and completed build alias", name, len(opened), len(linked)),
                )
                hits[name] = [opened, linked]
            data["positive_kernel_events"] = hits
            gz(d / "original.strace.gz", raw.encode())
            (d / "original.strace").unlink()
        save(d / "outcome.json", data)
        records[label] = data

    def finals():
        (a,) = [p for p in (work / "cache").iterdir() if p.is_dir()]
        return [p for p in a.iterdir() if p.is_dir() and not p.name.endswith("-working")]

    def ordered(mode):
        if (work / "cache").exists():
            shutil.rmtree(work / "cache")
        key = mode + "-"
        run(key + "a", writer, "a", "on")
        (a,) = finals()
        run(key + "b", writer, "b", "on")
        (b,) = [x for x in finals() if x != a]
        foreign = sha(a / "ohm-packed-query-cache.bin")
        for n in ("invalid", "invalid-repeat"):
            run(key + n, writer, "b", "on", "bad")
            check(b in finals() and a in finals(), "error mutated finalized history")
        run(key + "repair", writer, "b", "on")
        (c,) = [x for x in finals() if x != a]
        check(
            c != b and sha(a / "ohm-packed-query-cache.bin") == foreign,
            "new repaired versus frozen alternate",
        )
        forms = [(c / ("ohm-packed-" + n + ".bin")).is_file() for n in ("dep-graph", "query-cache")]
        check(forms == [not control, not control], ("parent/candidate physical repair discriminator", forms))
        if control:
            # Existing E writes the identical on-disk format on a true return. Qualify its real reader independently.
            run(key + "parent-switch-a", writer, "a", "on")
            run(key + "parent-switch-b", writer, "b", "on")
            a = next(
                x
                for x in finals()
                if x.name.split("-")[2].split("_")[1] == a.name.split("-")[2].split("_")[1]
            )
            (c,) = [x for x in finals() if x != a]
        members = {n: c / ("ohm-packed-" + n + ".bin") for n in ("dep-graph", "query-cache")}
        for n, p in members.items():
            raw = zlib.decompress(p.read_bytes())
            head, data = raw[11:].split(b"\0", 1)
            check(
                raw[0] == 1
                and raw[2] == 3
                and head.decode() == c.name.rsplit("-", 1)[0]
                and data.startswith(b"RSIC")
                and len(data) == int.from_bytes(raw[3:11], "little"),
                "actual build-table payload",
            )
        run(key + "unchanged-reader", "P", "b", mode, trace=members)
        if mode == "default":
            check(len(finals()) == 1, "single finalized session after disabling")
        run(key + "private-83", "P", "b", mode, "edit")
        run(key + "return-a", "P", "a", mode)
        run(key + "return-b", "P", "b", mode)
        for role in sorted(kits):
            for branch, kind in [("a", "ok"), ("b", "ok"), ("b", "edit")]:
                shutil.rmtree(work / "cache")
                run(key + "empty-" + role + "-" + branch + "-" + kind, role, branch, mode, kind)

    for mode in ("on", "default"):
        ordered(mode)
    result = {
        "kind": (
            "original parent repair red; actual packed true-switch reader positive"
            if control
            else "source candidate repairs; unmodified parent opens the actual output"
        ),
        "source": {k: subjects[k]["source"] for k in kits},
        "sdk_drivers": {r: v[2] for r, v in kits.items()},
        "states": records,
        "complete_native": {str(k): v for k, v in refs.items()},
    }
    save(root / "report.json", result)
    return result


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("root", type=Path)
    a.add_argument("subjects", type=Path)
    a.add_argument("--parent-control", action="store_true")
    x = a.parse_args()
    ret = fixture(x.root, json.loads(x.subjects.read_bytes()), x.parent_control)
    print(ret["kind"], len(ret["states"]))
