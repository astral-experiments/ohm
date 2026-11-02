"""Keep literal raw material, explicit semantic evidence and downstream behavior independent."""

from pathlib import Path
import gzip
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import tarfile

import service as s
import collector as collect

m = s.m


def toolkit(root, blobs):
    package = s.HERE / "metadata-kit.tar.xz"
    assert m.filesha(package) == s.case["kit_sha"]
    root.mkdir()
    with tarfile.open(package) as t:
        members = t.getmembers()
        assert len(members) == len(s.case["toolkit"]) == len({q.name for q in members})
        for q in members:
            assert (
                q.isfile()
                and q.name in s.case["toolkit"]
                and not q.name.startswith("/")
                and ".." not in Path(q.name).parts
            )
            target = root / q.name
            target.parent.mkdir(exist_ok=True, parents=True)
            data = t.extractfile(q).read()
            assert m.digest(data) == s.case["toolkit"][q.name]
            target.write_bytes(data)
    mod = root / s.case["kit_module"]
    (mod.parent / "blobs").symlink_to(blobs.resolve(), target_is_directory=True)
    return runpy.run_path(str(mod))


def complete_cold_oracle(d, one, two, dec, blobs, headers):
    assert one["all_public_sidecars"] == two["all_public_sidecars"] and set(
        one["workspace"]
    ) == set(two["workspace"])
    found = {}
    changed = {}
    unreconstructed = set()

    def check(p, a, b, workspace):
        if a == b:
            return
        if p in found:
            assert found[p]["warm"] == a and found[p]["cold"] == b
            return
        file = Path(p)
        assert file.suffix == ".rmeta" and file.name.startswith("lib")
        name = file.name[3:].split("-")[0]
        v = dec["check_delta"](a, b, name)
        assert all(v["checks"].values()) and v["physical_moved"], (name, v)
        if not v["exact_complete_bytes"]:
            assert (
                workspace
                and name in s.case["known_physical_kinds"]
                and set(v["physical_moved"])
                <= set(s.case["known_physical_kinds"][name])
            ), (p, v)
            unreconstructed.add(name)
        hs = []
        for item in (a, b):
            h = item[1]
            out = headers / (h + ".stdout")
            if not out.exists():
                raw = gzip.decompress((blobs / (h + ".gz")).read_bytes())
                assert [len(raw), m.digest(raw)] == item
                f = headers / "library.rmeta"
                f.write_bytes(raw)
                q = subprocess.run(
                    [m.RUSTC, "-Zls=root", f],
                    env=m.ENV,
                    capture_output=True,
                    timeout=30,
                )
                assert q.returncode == 0 and q.stdout and not q.stderr, (
                    name,
                    q.stderr[-700:],
                )
                out.write_bytes(q.stdout)
                f.unlink()
            hs.append(m.filesha(out))
        assert len(set(hs)) == 1
        found[p] = dict(**v, native_Zls_root=hs)
        changed[p] = workspace

    for p, x in one["workspace"].items():
        check(p, x, two["workspace"][p], True)
    for n, rows in one["externs"].items():
        rr = two["externs"][n]
        assert rows.keys() == rr.keys()
        for p, x in rows.items():
            rel = str(Path(p).relative_to(m.TARGET))
            if rel in one["workspace"]:
                assert one["workspace"][rel] == x and two["workspace"][rel] == rr[p]
                continue
            check(rel, x, rr[p], False)
    for n, rows in one["declared"].items():
        other = two["declared"][n]
        assert rows.keys() == other.keys()
        for p, x in rows.items():
            if p in one["workspace"]:
                assert one["workspace"][p] == x and two["workspace"][p] == other[p]
            else:
                assert x == other[p], ("declared fresh output", p)
    data = dict(
        all_guarded=True,
        all_workspace=len(one["workspace"]),
        raw_all_exact=not found,
        changes=found,
        fixed_input_owners_required=sorted(unreconstructed),
        scope="same-seed raw equality is separate; each unreconstructed independent cold serialization is disclosed",
    )
    m.save(d / "independent-cold.json", data)
    return data


def copied(output, content):
    if not output.exists() or output.read_bytes() != content:
        output.write_bytes(content)


def probes(out, state, role):
    out.mkdir()
    src = m.ROOT / "behavior"
    src.mkdir(exist_ok=True)
    dirs = sorted(
        {
            f.parent
            for pat in ("*.rlib", "*.rmeta", "*.so")
            for f in (m.TARGET / "debug").rglob(pat)
        }
    )
    metadata = {
        n: next(
            (m.TARGET / "debug/build" / n.replace("_", "-")).glob(
                "*/out/lib" + n + "-*.rmeta"
            )
        )
        for n in ("uv_client", "uv_configuration")
    }
    emitted = {}
    codes = {}
    cases = {
        "existing": (
            "pub const PRESENT: uv_configuration::TreeFormat = uv_configuration::TreeFormat::Text;",
            None,
        ),
        "schema": (
            "use uv_configuration::MetadataOutputVersion; fn twice<T: Copy>(v:T)->(T,T){(v,v)} pub fn parse(x:&str)->(MetadataOutputVersion,MetadataOutputVersion){twice(MetadataOutputVersion::from(x))}",
            "E0432" if state == "A" else None,
        ),
        "client": (
            "pub fn existing(c:&uv_client::RegistryClient)->&uv_client::CachedClient{let _=c.connectivity();c.cached_client()}",
            None,
        ),
        "client-negative": (
            "pub fn wrong(c:&uv_client::RegistryClient)->usize{c.cached_client()}",
            "E0308",
        ),
    }
    for name, (code, wrong) in cases.items():
        f = src / "production.rs"
        copied(f, (code + "\n").encode())
        r = out / (name + ".stderr")
        args = [
            m.RUSTC,
            "--edition=2024",
            "--crate-name",
            "ohm_22958_production_probe",
            "--crate-type",
            "lib",
            "--emit=metadata",
            "--error-format=json",
            f,
            "-o",
            src / "probe.rmeta",
        ]
        for nm, v in metadata.items():
            args.extend(["--extern", nm + "=" + str(v)])
        for directory in dirs:
            args.extend(["-L", "dependency=" + str(directory)])
        pr = subprocess.run(args, env=m.ENV, cwd=m.SRC, capture_output=True, timeout=50)
        r.write_bytes(pr.stderr)
        assert not pr.stdout
        errors = [json.loads(l) for l in pr.stderr.splitlines()]
        actual = [
            x["code"]["code"]
            for x in errors
            if x.get("level") == "error" and x.get("code")
        ]
        assert (
            (pr.returncode != 0 and actual == [wrong])
            if wrong
            else (pr.returncode == 0 and not actual)
        ), (name, state, actual, pr.stderr[-1300:])
        if wrong == "E0432":
            assert "MetadataOutputVersion" in errors[0]["message"]
        if wrong == "E0308":
            assert any("CachedClient" in str(x) for x in errors)
        codes[name] = [pr.returncode, actual]
        emitted[name] = list(map(str, args))
    parser = src / "parser"
    (parser / "src").mkdir(exist_ok=True, parents=True)
    for name in ("Cargo.toml", "Cargo.lock", "src/main.rs"):
        copied(parser / name, (s.HERE / "fixture" / name).read_bytes())
    original = (m.SRC / "crates/uv-configuration/src/output_format.rs").read_bytes()
    copied(parser / "src/output_format.rs", original)
    target = m.ROOT / ("fixture-" + role)
    env = dict(m.ENV, CARGO_TARGET_DIR=str(target))
    linked = {}
    for kind in ("existing", "schema"):
        args = [
            m.SDK / "bin/cargo",
            "build",
            "--locked",
            "--offline",
            "-j2",
            "--message-format=json",
        ] + (["--features", "schema"] if kind == "schema" else [])
        pr = subprocess.run(args, env=env, cwd=parser, capture_output=True, timeout=240)
        (out / (kind + ".cargo.stdout")).write_bytes(pr.stdout)
        (out / (kind + ".cargo.stderr")).write_bytes(pr.stderr)
        events = [json.loads(l) for l in pr.stdout.splitlines()]
        if (kind, state) == ("schema", "A"):
            assert pr.returncode != 0 and any(
                (z.get("message", {}).get("code") or {}).get("code") == "E0432"
                for z in events
            )
            linked[kind] = {"error": "E0432"}
            continue
        assert pr.returncode == 0, (kind, pr.stderr[-1200:])
        (exe,) = [
            Path(i["executable"])
            for i in events
            if i.get("reason") == "compiler-artifact" and i.get("executable")
        ]
        expect = b"columns, text\n" if kind == "existing" else b'"preview"\n'
        views = []
        for arg in (
            [None] if kind == "existing" else [None, "preview", "future-version", ""]
        ):
            v = subprocess.run(
                [exe] + ([] if arg is None else [arg]),
                cwd=parser,
                env=env,
                capture_output=True,
                timeout=8,
            )
            assert (v.returncode, v.stdout, v.stderr) == (0, expect, b"")
            views.append([arg, v.stdout.decode()])
        linked[kind] = {"actual": views, "binary": m.filesha(exe)}
    obj = {
        "codes": codes,
        "linked": linked,
        "verified_unchanged_client_methods": [
            "RegistryClient::cached_client",
            "RegistryClient::connectivity",
        ],
        "module": m.digest(original),
        "actual_metadata": {n: m.filesha(f) for n, f in metadata.items()},
    }
    m.save(out / "argv.json", emitted)
    m.save(out / "witness.json", obj)
    return obj


def observables(o):
    return dict(
        codes=o["codes"],
        linked={k: v.get("actual", v.get("error")) for k, v in o["linked"].items()},
        module=o["module"],
        unchanged=o["verified_unchanged_client_methods"],
    )
