"""Bind the settled Ruff link to its cold producer graph and the strict Cargo input marker."""

import gzip
import hashlib
import itertools
import json
import re
import stat
import struct
import subprocess
from pathlib import Path

from bindings import SDK, WILD, WORK, need, numbers, save, sha

MARK = "/dev/null/ohm-recheck-dependent-links"
BINARY = "path+file:///__public_ruff_source__/crates/ruff#0.16.7"
SWITCH_DIRTY = "051ce242f7e322de5461eb39ad55f6a52cd275b665490eb0c95afe678fb14d8c"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index#"
VERSIONS = {"serde_json": "1.0.151", "zmij": "1.0.10"}


def one(items, why):
    values = list(items)
    need(len(values) == 1, (why, len(values)))
    return values[0]


def flag(argv, key):
    return one((v for k, v in itertools.pairwise(argv) if k == key), key)


def sole_bin(dirty):
    row = one(dirty, "only one dirty unit on unchanged B")
    need(
        row["name"] == "ruff"
        and row["id"] == BINARY
        and row["kind"] == row["crate_types"] == ["bin"]
        and not row["profile"]["test"],
        "settled dirty unit was not the regular Ruff executable",
    )


def crop(cold, messages):
    """Take the actual cold native --extern operands, resolving each with Cargo's typed unit."""
    chain = {}
    for name, kind in (("ruff", "bin"), ("serde_json", "lib"), ("zmij", "lib")):
        row = one(
            (
                row
                for row in cold["rustcs"]
                if row["crate"] == name
                and row["mode"] == "full"
                and flag(row["argv"], "--crate-type") == kind
            ),
            (name, kind, "cold compiler"),
        )
        args = row["argv"]
        need(
            row["exe"] == args[0] == str(SDK / "bin/rustc") and flag(args, "--crate-name") == name,
            ("physical cold rustc", name),
        )
        obs = one(
            (
                m
                for m in messages
                if m.get("reason") == "compiler-artifact"
                and m["target"]["name"] == name
                and m["target"]["kind"] == [kind]
            ),
            (name, "Cargo artifact"),
        )
        out = Path(flag(args, "--out-dir"))
        need(
            out.name == "out" and out.parent.parent.name == name and out.is_relative_to(WORK),
            ("physical split output", out),
        )
        src = Path(obs["target"]["src_path"])
        item = {
            "pid": row["pid"],
            "package": obs["package_id"],
            "source": str(src),
            "out": str(out),
        }
        if kind == "lib":
            suffix = one(
                (
                    a.removeprefix("extra-filename=")
                    for k, a in itertools.pairwise(args)
                    if k == "-C" and a.startswith("extra-filename=")
                ),
                (name, "unit suffix"),
            )
            need(
                re.fullmatch(r"-[0-9a-f]{16}", suffix) and suffix[1:] == out.parent.name,
                ("registry unit suffix", name, suffix),
            )
            base = name + suffix
            item.update(
                rlib=str(out / ("lib" + base + ".rlib")),
                rmeta=str(out / ("lib" + base + ".rmeta")),
                depfile=str(out / (base + ".d")),
            )
            need(
                obs["package_id"] == REGISTRY + name + "@" + VERSIONS[name]
                and src.parts[-3:] == (name + "-" + VERSIONS[name], "src", "lib.rs")
                and str(src) in args
                and set(obs["filenames"]) == {item["rlib"], item["rmeta"]}
                and "--emit=dep-info,metadata,link" in args,
                ("registry producer, source and complete products", name),
            )
        else:
            need(
                src.parts[-4:] == ("crates", "ruff", "src", "main.rs")
                and "crates/ruff/src/main.rs" in args
                and obs["target"]["crate_types"] == ["bin"]
                and obs["executable"]
                and obs["filenames"] == [obs["executable"]],
                "cold Ruff binary",
            )
            item["executable"] = obs["executable"]
        chain[name] = item
        if name != "zmij":
            child = "serde_json" if name == "ruff" else "zmij"
            item["extern"] = sorted(
                a[len(child) + 1 :]
                for k, a in itertools.pairwise(args)
                if k == "--extern" and a.startswith(child + "=")
            )
    need(
        chain["ruff"]["extern"] == sorted([chain["serde_json"][k] for k in ("rlib", "rmeta")])
        and chain["serde_json"]["extern"] == [chain["zmij"]["rmeta"]],
        "actual Ruff bin -> serde_json -> zmij compiler operands",
    )
    return chain


def marker(data):
    # Strict Cargo 761ea115 serializes checksum-free records as v2. This particular
    # registry record has one build-root-relative path, no checksum, no env and LNK1[0].
    path = MARK.encode()
    prefix = (
        b"\x01\0\0\0\xff\x02"
        + struct.pack("<I", 1)
        + b"\x01"
        + struct.pack("<I", len(path))
        + path
        + b"\0"
        + bytes(4)
        + b"LNK1"
        + bytes(4)
    )
    need(
        len(data) == 97 and data[:-32] == prefix,
        "wrong 97-byte zmij Cargo record or LNK1 path/index",
    )
    digest = (
        subprocess.check_output(["b3sum", "--no-names"], input=data[:-32], text=False)
        .decode()
        .strip()
    )
    need(
        data[-32:].hex()
        == digest
        == "b9fce86fee9787064ebd35b37ecd70147892e250e1ff7f8d2ba67a2456e582de",
        "wrong zmij LNK1 BLAKE3",
    )
    return digest


def make_rules(data, leaf):
    src = Path(leaf["source"])
    sources = [str(src), str(src.with_name("traits.rs"))]
    need(
        all(not any(c.isspace() or c in ":\\" for c in s) for s in sources),
        "ambiguous locked source path",
    )
    rules = {}
    for line in data.decode().splitlines():
        if not line:
            continue
        if line == "# ohm-raw-checksum-paths-v2":
            continue
        lhs, sep, rhs = line.partition(":")
        need(
            sep and lhs not in rules and (not rhs or rhs.startswith(" ")),
            ("ambiguous zmij rule", line),
        )
        rules[lhs] = rhs.split()
    expected = {
        leaf["depfile"]: sources,
        leaf["rlib"]: [*sources, MARK],
        leaf["rmeta"]: [*sources, MARK],
        **{p: [] for p in [*sources, MARK]},
    }
    need(
        rules == expected,
        ("zmij rustc output, ordinary source and phony marker rules", rules),
    )
    return rules


def physical(path):
    p = Path(path)
    need(
        p.resolve(strict=True) == p and stat.S_ISREG(p.lstat().st_mode),
        ("noncanonical file", p),
    )
    return {"path": str(p), "identity": numbers(p), "sha256": sha(p)}


def emitted(chain, where):
    leaf = chain["zmij"]
    encoded = Path(leaf["out"]).parent / "fingerprint/dep-lib-zmij"
    files = {key: physical(leaf[key]) for key in ("rlib", "rmeta", "depfile", "source")}
    files["traits"] = physical(Path(leaf["source"]).with_name("traits.rs"))
    files["encoded"] = physical(encoded)
    raw = Path(leaf["depfile"]).read_bytes()
    data = encoded.read_bytes()
    for key, body, dest in (
        ("depfile", raw, "zmij.d"),
        ("encoded", data, "dep-lib-zmij"),
    ):
        need(
            hashlib.sha256(body).hexdigest() == files[key]["sha256"],
            ("changed while reading", key),
        )
        with (where / dest).open("xb") as f:
            f.write(body)
    return {"files": files, "cargo_link_blake3": marker(data), "rustc_rules": make_rules(raw, leaf)}


def link(physical_execs, chain):
    r = one(physical_execs["rustcs"], "unchanged native rustc")
    w = one(physical_execs["wild_processes"], "unchanged native Wild linker")
    root = Path(chain["ruff"]["out"])
    recipe = str(root / "ruff.rlink")
    exe = str(root / "ruff")
    args = r["argv"]
    need(
        r["mode"] == "link-only"
        and r["crate"] == flag(args, "--crate-name") == "ruff"
        and flag(args, "--crate-type") == "bin"
        and flag(args, "--out-dir") == str(root)
        and r["exe"] == args[0] == str(SDK / "bin/rustc")
        and [v for k, v in itertools.pairwise(args) if k == "-Z" and v == "link-only"]
        == ["link-only"]
        and [v for v in args if v.endswith(".rlink")] == [recipe],
        "unexpected rustc or foreign saved recipe on settled Ruff link",
    )
    need(
        physical_execs["wild"] == 1
        and not physical_execs["other_linkers"]
        and w["exe"] == w["argv"][0] == str(SDK / WILD)
        and w["output"] == flag(w["argv"], "-o") == exe
        and [v for v in w["argv"] if Path(v).name.startswith("libzmij-") and v.endswith(".rlib")]
        == [chain["zmij"]["rlib"]],
        "wrong physical Wild, output or native zmij archive",
    )
    return {
        "rustc": r["pid"],
        "wild": w["pid"],
        "recipe": recipe,
        "output": exe,
        "linked_zmij": chain["zmij"]["rlib"],
    }


def read(path):
    return (
        json.loads(gzip.decompress(path.read_bytes()))
        if path.suffix == ".gz"
        else json.loads(path.read_bytes())
    )


def collect(where, phase, native, messages, reported_cli):
    cold = native if phase == "cold-A" else read(where.parent / "cold-A/native-execs.json.gz")
    chain = crop(cold, messages)
    proof = emitted(chain, where)
    receipt = {"cold": chain, "emitter": proof}
    if phase != "cold-A":
        started = read(where.parent / "cold-A/settled-origin.json")
        need(
            started["cold"] == chain and started["emitter"] == proof,
            "cold native origin or its bytes changed",
        )
        rp = Path(chain["ruff"]["out"]) / "ruff.rlink"
        recipe = physical(rp)
        data = rp.read_bytes()
        need(
            data.startswith(b"rustlink\0\0\0\x01")
            and len(data) > 12
            and hashlib.sha256(data).hexdigest() == recipe["sha256"],
            "invalid saved native recipe",
        )
        receipt["recipe"] = recipe
        if phase == "return-B":
            with (where / "settled-ruff.rlink.gz").open("xb") as f:
                f.write(gzip.compress(data, compresslevel=3, mtime=0))
        else:
            prior = read(where.parent / "return-B/settled-origin.json")
            need(
                prior["recipe"] == recipe and prior["emitter"] == proof,
                "settled native inputs changed",
            )
            actual = link(native, chain)
            returned = Path(chain["ruff"]["executable"])
            output = Path(actual["output"])
            need(
                str(returned) == str(reported_cli)
                and returned == WORK / "target/debug/ruff"
                and output.samefile(returned)
                and output.resolve(strict=True) == output,
                "the real Wild output does not own the returned Ruff executable",
            )
            receipt.update(
                link=actual,
                output_identity=numbers(output),
                returned_identity=numbers(returned),
            )
    save(where / "settled-origin.json", receipt)


def watched_after(where, tree):
    before = read(where / "watched-git-files.json")
    need(
        before == read(where.parent / "return-B/watched-git-files.json"),
        "watched Ruff source changed before the repeat",
    )
    ref = (tree / ".git/HEAD").read_text().strip().removeprefix("ref: ")
    need(
        ref.startswith("refs/heads/") and set(before) == {"HEAD", ref},
        "missing watched Ruff Git ref",
    )
    after = {}
    for name in before:
        file = tree / ".git" / name
        ident = physical(file)
        dev, ino, _, _, mt, ct = ident["identity"]
        after[name] = {
            "device": dev,
            "inode": ino,
            "mtime_ns": mt,
            "ctime_ns": ct,
            "sha256": ident["sha256"],
        }
    need(after == before, "watched Ruff Git refs changed in the settled command")
    save(where / "watched-git-files-after.json", after)
