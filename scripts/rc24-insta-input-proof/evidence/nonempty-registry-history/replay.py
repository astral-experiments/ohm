"""Exercise a genuine old nonempty generated-file record on upgrade, outside hardware cohorts."""

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import zlib
from pathlib import Path

import tomllib

here = Path(__file__).resolve().parent


def sha(b):
    return hashlib.sha256(b).hexdigest()


def write(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(v)


def dump(p, x):
    write(p, json.dumps(x, indent=2, sort_keys=True) + "\n")


def cmd(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, **kw)


def identity(p):
    s = p.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]


def parse(data):
    f = io.BytesIO(data)

    def take(n):
        v = f.read(n)
        assert len(v) == n
        return v

    def num(n):
        return int.from_bytes(take(n), "little")

    def body():
        return take(num(4)).decode()

    assert take(5) == b"\1\0\0\0\xff"
    version = num(1)
    assert version in (2, 4, 5, 6)
    files = {}
    for _ in range(num(4)):
        kind = num(1)
        name = body()
        coded = num(1)
        assert coded in (0, 1) and name not in files
        files[name] = [kind, num(8), body()] if coded else [kind, None, None]
    env = {}
    for _ in range(num(4)):
        key = body()
        yes = num(1)
        assert yes in (0, 1)
        env[key] = body() if yes else None
    assert not f.read()
    return {"version": version, "files": files, "env": env}


def rustpkg(name):
    return f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2021"\n'


def package(d, crates, idx, name, files, deps):
    dst = crates / name / "0.1.0/download"
    dst.parent.mkdir(parents=True)
    with tarfile.open(dst, "w:gz") as ar:
        for rel, body in sorted(files.items()):
            content = body.encode()
            t = tarfile.TarInfo(name + "-0.1.0/" + rel)
            t.size = len(content)
            t.mode = 0o644
            t.mtime = 1153704088
            ar.addfile(t, io.BytesIO(content))
    row = {
        "name": name,
        "vers": "0.1.0",
        "deps": [
            {
                "name": x,
                "req": "^0.1.0",
                "optional": False,
                "default_features": True,
                "features": [],
                "target": None,
                "kind": "normal",
                "registry": None,
            }
            for x in deps
        ],
        "cksum": sha(dst.read_bytes()),
        "features": {},
        "yanked": False,
        "links": None,
    }
    f = idx / name[:2] / name[2:4] / name
    write(f, json.dumps(row) + "\n")
    return row["cksum"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--signed", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--legacy-control", action="store_true")
    ap.add_argument("--published-parent", action="store_true")
    ap.add_argument("--pristine-source", action="store_true")
    ap.add_argument("--predecessor", choices=["matched23", "cargo23", "from24"])
    ap.add_argument("--first-clean", action="store_true")
    a = ap.parse_args()
    assert (
        not a.first_clean
        or a.published_parent
        and not (a.pristine_source or a.legacy_control or a.predecessor)
    )
    d = a.root.resolve()
    assert not d.exists() and shutil.disk_usage(d.parent).free > 20 * 2**30
    d.mkdir()
    ev = d / "evidence"
    ev.mkdir()
    src = d / "application"
    prov = d / "provider"
    crates = d / "objects"
    index = d / "index"
    index.mkdir()
    gen = "pub const GENERATED: u8 = 83;"
    manifest = rustpkg("v5consumer") + '\n[dependencies]\nguardprovider="0.1.0"\n'
    library = 'include!(concat!(env!("OUT_DIR"), "/generated.rs"));\npub fn result()->(u8,u8,u8){(guardprovider::value(), 17u8, GENERATED)}\n'
    write(
        index / "config.json",
        json.dumps({"dl": crates.as_uri() + "/{crate}/{version}/download"}),
    )
    pack = package(
        d,
        crates,
        index,
        "v5consumer",
        {
            "Cargo.toml": manifest,
            "src/lib.rs": library,
            "build.rs": 'fn main(){println!("cargo::rerun-if-changed=build.rs");std::fs::write(std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("generated.rs"),"'
            + gen
            + '").unwrap();}\n',
        },
        ["guardprovider"],
    )
    package(
        d,
        crates,
        index,
        "guardprovider",
        {
            "Cargo.toml": rustpkg("guardprovider"),
            "src/lib.rs": "pub fn value()->u8{100}",
        },
        [],
    )
    for args in (
        ["init", "-q", "-b", "master"],
        ["add", "--", "."],
        [
            "-c",
            "user.name=Charlie Marsh",
            "-c",
            "user.email=charlie.r.marsh@gmail.com",
            "commit",
            "-qm",
            "Register checksum and generated-source fixture",
        ],
    ):
        cmd(["git", *args], cwd=index)
    write(
        src / "Cargo.toml",
        rustpkg("partialv5app")
        + '\n[dependencies]\nv5consumer="0.1.0"\n[patch.crates-io]\nguardprovider={path="../provider"}\n[workspace]\n',
    )
    write(
        src / ".cargo/config.toml",
        '[source.crates-io]\nreplace-with="proof"\n[source.proof]\nregistry="'
        + index.as_uri()
        + '"\n',
    )
    write(
        src / "src/main.rs",
        'fn main(){let (a,b,c)=v5consumer::result();println!("{a} {b} {c}");}\n',
    )
    write(prov / "Cargo.toml", rustpkg("guardprovider"))

    def upstream(v):
        write(
            prov / "src/lib.rs",
            f"#[inline(never)] fn internal()->u8{{{v}}}\n#[inline(never)] pub fn value()->u8{{internal()}}\n",
        )

    upstream(7)
    sdk = d / "active-sdk"
    (sdk / "bin").mkdir(parents=True)
    ru = d / "rustup"
    home = d / "cargo-home"
    target = d / "target"
    build = d / "build"
    for f in a.signed.iterdir():
        if f.name != "bin":
            (sdk / f.name).symlink_to(f, target_is_directory=f.is_dir())
    for f in (a.signed / "bin").iterdir():
        if f.name != "cargo":
            (sdk / "bin" / f.name).symlink_to(f)
    tools = {"parent": a.parent, "candidate": a.candidate}
    fixed = {
        "parent": "b05c0f1a01f8cae3ccb7446647fcb7d9b5a36c3dfabc340a78a8b189561036b6",
        "candidate": "32df98560d4ac57c4c959c762095a3afe6a3bbe62b44d8fc6e6bf8071f53a53e",
    }
    if a.published_parent:
        assert a.parent.resolve() == (a.signed / "bin/cargo").resolve()
        fixed["parent"] = (
            "a4faa288657042d02767a38812c7498218dfcafc945abfe3b4a44c07323a1a24"
        )
    if a.predecessor:
        published23 = "f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee"
        published24 = "a4faa288657042d02767a38812c7498218dfcafc945abfe3b4a44c07323a1a24"
        fixed["parent"] = published24 if a.predecessor == "from24" else published23
        fixed["candidate"] = published23
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(d / "home"),
        "LANG": "C.UTF-8",
        "RUSTUP_HOME": str(ru),
        "CARGO_HOME": str(home),
        "CARGO_TARGET_DIR": str(target),
        "CARGO_BUILD_BUILD_DIR": str(build),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
    }
    (d / "home").mkdir()
    active = None

    def select(role):
        nonlocal active
        if active != role:
            assert sha(tools[role].read_bytes()) == fixed[role]
            update = sdk / "bin/cargo.next"
            shutil.copyfile(tools[role], update)
            update.chmod(0o755)
            os.replace(update, sdk / "bin/cargo")
            active = role

    select("parent")
    cmd(["rustup", "toolchain", "link", "ohm", sdk], env=env)
    assert (
        b"d57fd1515986dccecdcece8da85e651bfb4b81f9"
        if a.predecessor == "matched23"
        else b"f5a51d8cc3e76236c2d0f17d495d59ebb03306e4"
    ) in cmd(["rustc", "+ohm", "-vV"], env=env).stdout
    for label, args in [
        ("lock", ["generate-lockfile"]),
        ("fetch", ["fetch", "--locked"]),
    ]:
        r = subprocess.run(
            ["cargo", "+ohm", *args], cwd=src, env=env, capture_output=True, check=False
        )
        (ev / (label + ".stderr")).write_bytes(r.stderr)
        assert r.returncode == 0, r.stderr[-500:]
    lock = tomllib.loads((src / "Cargo.lock").read_text())
    assert (
        len(lock["package"]) == 3
        and next(k for k in lock["package"] if k["name"] == "v5consumer")["checksum"]
        == pack
    )
    env["CARGO_NET_OFFLINE"] = "true"
    (settings,) = (home / "registry/src").glob("*/v5consumer-0.1.0/src/lib.rs")
    original = settings.read_bytes()
    assert original == library.encode()
    sst = identity(settings)
    original_mode = settings.stat().st_mode

    def mutate(word):
        assert len(word) == 4 and identity(settings) == sst
        current = settings.stat()
        settings.chmod(original_mode | stat.S_IWUSR)
        settings.write_bytes(original.replace(b"17u8", word))
        os.utime(settings, ns=(current.st_atime_ns, sst[3]))
        settings.chmod(original_mode)
        assert identity(settings) == sst

    def fresh(group):
        for p in (target, build):
            if p.exists():
                assert p.parent == d and not p.is_symlink()
                p.rename(d / (p.name + "." + group))
        assert not target.exists() and not build.exists()

    rows = []
    native_dir = ev / "native"
    native_dir.mkdir()
    saved_d = None

    def visit(name, role, exit=0, wanted=None):
        nonlocal saved_d
        select(role)
        o = ev / name
        o.mkdir()
        args = [
            "cargo",
            "+ohm",
            "build",
            "--locked",
            "--offline",
            "-j1",
            "--message-format=json",
        ]
        r = subprocess.run(args, cwd=src, env=env, capture_output=True, check=False)
        (o / "stdout.jsonl").write_bytes(r.stdout)
        (o / "stderr").write_bytes(r.stderr)
        assert r.returncode == exit, (name, r.returncode, r.stderr[-400:])
        msgs = [json.loads(l) for l in r.stdout.splitlines() if l.startswith(b"{")]
        assert msgs[-1] == {"reason": "build-finished", "success": exit == 0}
        if exit:
            assert any(
                m["reason"] == "compiler-message"
                and (m["message"].get("code") or {}).get("code") == "E0308"
                and any(
                    v["is_primary"] and v["file_name"] == str(settings)
                    for v in m["message"]["spans"]
                )
                for m in msgs
            )
        hs = [p for root in (target, build) for p in root.rglob("dep-lib-v5consumer")]
        assert len(hs) == 1, (name, hs)
        p = hs[0]
        raw = p.read_bytes()
        parsed = parse(raw)
        (o / "translated.bin").write_bytes(raw)
        rels = p.relative_to(build if p.is_relative_to(build) else target)
        if saved_d is None:
            saved_d = str(rels)
        assert saved_d == str(rels)
        exe = target / "debug/partialv5app"
        elf = exe.read_bytes()
        h = sha(elf)
        nf = native_dir / (h + ".z")
        if not nf.exists():
            nf.write_bytes(zlib.compress(elf, 6))
        runtime = cmd([exe], cwd=src, env=env).stdout.decode().strip()
        assert wanted is None or runtime == wanted, (name, runtime, wanted)
        generated = [
            (p, x) for p, x in parsed["files"].items() if p.endswith("/generated.rs")
        ]
        assert (
            len(generated) == 1
            and generated[0][1][0] in (0, 1)
            and (generated[0][1][2] or parsed["version"] == 2)
        )
        row = {
            "name": name,
            "role": role,
            "exit": exit,
            "display": runtime,
            "elf": h,
            "wire_sha256": sha(raw),
            "wire": parsed,
            "wire_path": str(rels),
            "source_stat": identity(settings),
            "source_sha256": sha(settings.read_bytes()),
            "nominal": [
                m["target"]["name"]
                for m in msgs
                if m["reason"] == "compiler-artifact" and not m["fresh"]
            ],
        }
        products = {}
        for pkg in ("guardprovider", "v5consumer"):
            result = {}
            for key, pattern in [
                ("public", "lib-" + pkg + ".public-api-hash"),
                ("rmeta", "lib" + pkg + "-*.rmeta"),
            ]:
                files = {
                    q.resolve() for root in (target, build) for q in root.rglob(pattern)
                }
                assert len(files) <= 1
                if files:
                    q = files.pop()
                    content = q.read_bytes()
                    (o / (pkg + "." + key)).write_bytes(content)
                    result[key] = {
                        "sha256": sha(content),
                        "bytes": len(content),
                        "identity": identity(q),
                    }
                    if key == "public":
                        result[key]["value"] = json.loads(content)
            products[pkg] = result
        row["products"] = products
        dump(o / "result.json", row)
        rows.append(row)
        print(
            name,
            role,
            exit,
            runtime,
            parsed["version"],
            len(parsed["files"]),
            flush=True,
        )
        return row

    dump(
        ev / "registration.json",
        {
            "cargo": fixed,
            "rustc": cmd(["rustc", "+ohm", "-vV"], env=env).stdout.decode(),
            "physical_cargo": {
                role: cmd([path, "-Vv"]).stdout.decode() for role, path in tools.items()
            },
            "attribution": a.predecessor,
            "package_archive": pack,
            "registry_index": cmd(["git", "rev-parse", "HEAD"], cwd=index)
            .stdout.decode()
            .strip(),
            "precondition": "actual nonempty original generated-file record retaining zero package source checksums; fixed installations and unchanged physical source dev/ino/size/nanosecond mtime",
            "trace": "native programs, raw object identity, generated checksum and Cargo artifacts; no local exec counter",
        },
    )
    old = visit("old-parent", "parent", wanted="7 17 83")
    assert len(old["wire"]["files"]) == 1
    assert old["wire"]["version"] in (
        (2, 4) if a.predecessor in ("matched23", "cargo23") else (5,)
    ) and not any(
        x[0] in (2, 3) or k == "src/lib.rs" for k, x in old["wire"]["files"].items()
    )
    visit("settled-parent", "parent", wanted="7 17 83")
    upstream(9)
    if a.pristine_source:
        assert settings.read_bytes() == original and identity(settings) == sst
        changed = visit("prerequisite-alone", "parent", wanted="9 17 83")
        settled = visit("settled-prerequisite-alone", "parent", wanted="9 17 83")
        fresh("original-pristine-edit")
        oracle = visit("pristine-independent-empty", "parent", wanted="9 17 83")
        assert changed["elf"] == settled["elf"] == oracle["elf"]
        assert all(
            x["source_sha256"] == sha(original) and x["source_stat"] == sst
            for x in rows
        )
        dump(
            ev / "complete.json",
            {"rows": rows, "matched_independently_empty": oracle["elf"]},
        )
        return
    mutate(b"29u8")
    if a.predecessor:
        first = visit("predecessor-first-edit", "candidate")
        second = visit("predecessor-unchanged", "candidate")
        fresh("original-predecessor")
        oracle = visit("predecessor-independent-empty", "candidate", wanted="9 29 83")
        assert (
            first["products"]["guardprovider"]["public"]["value"]
            == old["products"]["guardprovider"]["public"]["value"]
        )
        assert all(x["source_stat"] == sst for x in rows)
        assert all(
            x["source_sha256"] == first["source_sha256"] for x in [second, oracle]
        )
        dump(
            ev / "complete.json",
            {
                "rows": rows,
                "first_matches_empty": first["elf"] == oracle["elf"],
                "repeat_matches_empty": second["elf"] == oracle["elf"],
                "attribution": a.predecessor,
            },
        )
        return
    if a.legacy_control:
        before = visit("old-reader-real-edit", "parent")
        again = visit("old-reader-unchanged", "parent")
        after = visit("upgrade-without-new-prerequisite", "candidate")
        stable = old["products"]["guardprovider"]["public"]["value"]
        assert before["products"]["guardprovider"]["public"]["value"] == stable
        assert before["wire"]["version"] == 5
        upstream(8)
        recovered = visit(
            "new-reader-after-prerequisite", "candidate", wanted="8 29 83"
        )
        assert (
            recovered["wire"]["version"] == 6
            and recovered["wire"]["files"]["src/lib.rs"][0] == 2
        )
        assert recovered["products"]["guardprovider"]["public"]["value"] == stable
        fresh("original-legacy-control")
        oracle = visit("new-reader-independent-empty", "candidate", wanted="8 29 83")
        assert recovered["elf"] == oracle["elf"]
        upstream(9)
        fresh("oracle-eight")
        old_nine = visit(
            "published-reader-empty-at-original-edit", "parent", wanted="9 29 83"
        )
        fresh("oracle-nine-parent")
        new_nine = visit(
            "new-reader-empty-at-original-edit", "candidate", wanted="9 29 83"
        )
        assert old_nine["elf"] == new_nine["elf"]
        assert all(x["source_stat"] == sst for x in rows)
        dump(
            ev / "complete.json",
            {
                "rows": rows,
                "old_reader_on_changed_bytes": before["display"],
                "old_reader_settled": again["display"],
                "new_reader_before_next_prerequisite": after["display"],
                "physical_public_api_of_prerequisite": stable,
                "matched_independently_empty": oracle["elf"],
            },
        )
        return
    v = visit("upgraded-real-edit", "candidate", wanted="9 29 83")
    assert (
        old["products"]["guardprovider"]["public"]["value"]
        == v["products"]["guardprovider"]["public"]["value"]
    )
    assert (
        old["products"]["guardprovider"]["rmeta"]["sha256"]
        != v["products"]["guardprovider"]["rmeta"]["sha256"]
    )
    assert v["wire"]["version"] == 6 and v["wire"]["files"]["src/lib.rs"][0] == 2
    visit("settled-candidate", "candidate", wanted="9 29 83")
    upstream(8)
    mutate(b"true")
    visit("first-invalid", "candidate", 101, "9 29 83")
    visit("second-invalid", "candidate", 101, "9 29 83")
    mutate(b"17u8")
    restored = visit("repaired-candidate", "candidate", wanted="8 17 83")
    fresh("retained-history")
    empty = visit("empty-candidate", "candidate", wanted="8 17 83")
    assert restored["elf"] == empty["elf"] and v["elf"] != old["elf"]
    if a.first_clean:
        upstream(9)
        mutate(b"29u8")
        fresh("kept-independent-repair")
        first_oracle = visit("empty-first-candidate", "candidate", wanted="9 29 83")
        assert v["elf"] == first_oracle["elf"]
        assert (
            v["products"]["v5consumer"]["rmeta"]["sha256"]
            == first_oracle["products"]["v5consumer"]["rmeta"]["sha256"]
        )
    assert all(x["source_stat"] == sst for x in rows)
    dump(
        ev / "complete.json",
        {
            "rows": rows,
            "exact_repair": empty["elf"],
            "source_stat": sst,
            "native_sha256s": sorted(x.stem for x in native_dir.iterdir()),
        },
    )


if __name__ == "__main__":
    main()
