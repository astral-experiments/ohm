"""Run ordinary signed Rust/Cargo histories; every native invocation finishes its normal link."""

from collections import Counter
import gzip, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "e2e-existing-output")]
import audit, census_source, certificate

b, w, P = audit.b, audit.w, audit.P


def dump(out, data):
    b.write(P / out, data)


def check_hash(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def name(output, specs):
    distinct = [s for s in specs if str(output).endswith(s)]
    assert len(distinct) == 1, (output, distinct)
    return distinct[0]


def stage(tag, env, meta, state, specs, expected_image, sign=False):
    before = set(state.glob("actor-*.tsv"))
    inv = b.inventory(tag, env, meta)
    assert len(inv["executables"]) == 102 and inv["state"] == w.git("rev-parse", "HEAD")
    observed = sorted(set(state.glob("actor-*.tsv")) - before)
    results = {}
    signed = {}
    for path, row in inv["executables"].items():
        matches = [k for k in specs if path.endswith(k)]
        if matches:
            (key,) = matches
            assert row["unit"] == specs[key]["owner"] and key not in signed
            signed[key] = row["elf"]["sha256"]
    assert len(signed) == 50
    e2e = w.root / inv["binary"]
    assert (
        b.verdict(e2e, tag + "-typed-verdict", env, 0) == audit.contact.LITERALS["list"]
    )
    if sign:
        assert not observed
        return signed, e2e
    for file in observed:
        assert file.stat().st_size < 48 << 20
        raw = file.read_bytes()
        text = raw.decode()
        args = [
            json.loads(row.split("\t", 2)[2])
            for row in text.splitlines()
            if row.startswith("ARG\t")
        ]
        dest = Path(args[args.index("-o") + 1])
        key = name(dest, specs)
        assert (
            key not in results and dest.is_relative_to(w.root) and not dest.is_symlink()
        )
        log = P / tag / (key.split("/")[-1] + ".tsv.gz")
        log.write_bytes(gzip.compress(raw, compresslevel=2, mtime=0))
        spec = dict(specs[key], suffix=key)
        note = {
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "log": log.name,
            "qualified": False,
            "output": str(dest),
            "published_sha256": signed[key],
        }
        try:
            parse = certificate.projections(text, spec)
        except (AssertionError, ValueError, KeyError, IndexError) as error:
            import traceback

            note["refusal"] = {
                "type": type(error).__name__,
                "details": str(error)[:500],
                "last": traceback.format_tb(error.__traceback__)[-1].strip(),
            }
            results[key] = note
            continue
        assert parse["image_b3"] in (expected_image, "dynamic-or-unknown")
        emitted = parse["emitted"]
        st = dest.stat()
        assert (st.st_dev, st.st_ino, st.st_size) == (
            emitted["dev"],
            emitted["ino"],
            emitted["bytes"],
        )
        assert (
            audit.donor.full_b3(dest) == emitted["b3"]
            and check_hash(dest) == signed[key]
        )
        note.update(parse, qualified=True)
        results[key] = note
    assert results.keys() == specs.keys(), (
        tag,
        len(results),
        sorted(specs.keys() - results.keys()),
    )
    assert sum(f.stat().st_size for f in (P / tag).glob("*.tsv.gz")) < 150 << 20
    dump(tag + "-native.json.gz", results)
    return results, e2e


def main():
    assert (
        os.environ["REVIEWED_HEAD"] == os.environ["GITHUB_SHA"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    )
    assert (
        w.git("rev-parse", "HEAD") == b.NEW
        and w.git("rev-parse", "HEAD^") == b.OLD
        and w.hf(w.src / "sdk.json") == b.SPEC["sdk_manifest"]
    )
    assert shutil.disk_usage(w.root).free > 45 * 2**30
    w.guard()
    b.save_elf = w.hf
    spec = json.loads((HERE / "roles.json").read_bytes())
    basis = json.loads((HERE / "source-preflight.json").read_bytes())
    assert len(spec) == 50 and check_hash(HERE / "roles.json") == basis["roles_sha256"]
    dump(
        "admission.json",
        {
            "head": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "registration": basis,
            "sdk_manifest": b.SPEC["sdk_manifest"],
            "edit": (b.OLD, b.NEW),
            "bypass_compiled": False,
        },
    )
    env = w.install()
    state = w.root / "native-donor-state"
    state.mkdir()
    subprocess.run(
        [
            "cc",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            HERE.parent / "whole_count.c",
            "-o",
            w.root / "whole_count",
        ],
        check=True,
    )
    stock, llvm = audit.build(
        env, source=census_source.apply, registration=HERE / "source-preflight.json"
    )
    live = w.sdk / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    image = audit.donor.full_b3(live)
    dump(
        "physical-images.json",
        {
            "source_static_sha256": check_hash(live),
            "proc_image_b3": image,
            "stock_sha256": check_hash(stock),
            "llvm_sha256": check_hash(llvm),
        },
    )
    b.select(b.OLD)
    registry = b.inputs(env)
    dump("registry.json.gz", registry)
    meta = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "+ohm",
                "metadata",
                "--format-version=1",
                "--locked",
                "--offline",
                "--no-deps",
            ],
            cwd=w.work,
            env=env,
        )
    )
    assert len(meta["workspace_default_members"]) == 55
    data = {}
    signed = {}
    for tag in (
        "old",
        "edit",
        "first-unchanged",
        "second-unchanged",
        "third-unchanged",
    ):
        if tag == "edit":
            b.select(b.NEW)
            assert (
                b.verdict(e2e, "withheld-old-on-genuine-new", env, 101)
                == audit.contact.LITERALS["list"]
            )
        data[tag], e2e = stage(tag, env, meta, state, spec, image)
    live = w.sdk / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    assert w.hf(stock) == audit.donor.WILD
    staging = live.parent / "replace-with-exact-distributor"
    shutil.copy2(stock, staging)
    os.replace(staging, live)
    assert w.hf(live) == audit.donor.WILD
    for path in (w.target, w.shared, w.home):
        assert path.parent == w.root and path.is_dir() and not path.is_symlink()
        shutil.rmtree(path)
    b.PHYSICAL.clear()
    assert b.inputs(env) == registry
    for tag in (
        "independent-clean",
        "signed-first-unchanged",
        "signed-second-unchanged",
    ):
        signed[tag], e2e = stage(tag, env, meta, state, spec, image, True)
    result = {}
    for prev, curr in (
        ("old", "edit"),
        ("edit", "first-unchanged"),
        ("first-unchanged", "second-unchanged"),
        ("second-unchanged", "third-unchanged"),
    ):
        rows = {
            k: certificate.classify(
                data[prev].get(k), data[curr].get(k), signed["independent-clean"][k]
            )
            for k in spec
        }
        result[curr] = {
            "donor": prev,
            "qualified": sorted(k for k, r in rows.items() if not r),
            "refused": {k: r for k, r in rows.items() if r},
            "frequencies": dict(
                Counter(reason for rs in rows.values() for reason in rs)
            ),
        }
    dump("independent-signed.json.gz", signed)
    dump("all-50-decisions.json", result)


if __name__ == "__main__":
    main()
