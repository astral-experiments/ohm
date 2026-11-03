"""Independently read all physical P/C raw Ruff edits, metadata, runnable native files, and controls."""

from collections import Counter
from pathlib import Path
import argparse, hashlib, json, re, shutil, subprocess, sys, tempfile, zipfile

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import verify_scope_native as physical
import scope_rdr as rdr

KNOWN = {
    "P": (
        "259ad7069e47eaf08cf106f187b2b6393f7fd7c2",
        "0d49e63d32705ff17d1bc2f29e9f504e92a674a0926b15d4e333db37a437f0d1",
    ),
    "C": (
        "a7fc5bc7f90966e6e9a92f9239e3e304e79b2f3f",
        "164ae65b41ff9db3b6853b4d66ed39c36a4f10d5082673b77487becfe8b20a58",
    ),
}
OWNERS = ("ruff_linter", "ruff_graph", "ruff_workspace", "ruff_markdown")
STAGES = ("old", "edit", "empty-new")


def crypto(raw):
    return hashlib.sha256(raw).hexdigest()


def load_owners(z, label, symbols, tables):
    where = label + "/"
    per = {}
    for stage in STAGES:
        stated = json.loads(z.read(where + "scope-" + stage + "/scope-rmetas.json"))
        assert set(stated) == set(OWNERS)
        per[stage] = {}
        for owner in OWNERS:
            witness = stated[owner]
            buf = z.read(where + "members/" + witness["sha256"] + ".rmeta.zst")
            assert crypto(buf) == witness["zstd_sha256"]
            raw = subprocess.run(
                ["zstd", "-qdc"], input=buf, stdout=subprocess.PIPE, check=True
            ).stdout
            assert len(raw) == witness["bytes"] and crypto(raw) == witness["sha256"]
            typed = {}
            head, defs, rows, expn, deps = rdr.decode(
                raw,
                symbols,
                tables,
                owner,
                "rustc 1.99.0-dev (Ohm metadata 3)",
                typed=typed,
            )
            scopes = {v for v in typed["visibility"].values() if v is not None}
            mutable = len(scopes - rows.keys())
            per[stage][owner] = (
                head,
                defs,
                rows,
                expn,
                deps,
                witness["bytes"],
                mutable,
            )
            del raw, typed
    out = {}
    for owner in OWNERS:
        stages = [per[s][owner] for s in STAGES]

        def compare(a, b):
            (ha, da, ra, ea, xa, _, _), (hb, db, rb, eb, xb, _, _) = a, b
            assert da == db and xa.keys() == xb.keys() and ha["stable"] == hb["stable"]
            common = ra.keys() & rb.keys()
            changed = {k for k in common if ra[k] != rb[k]}
            return dict(
                local_rows=[len(ra), len(rb)],
                added=len(rb.keys() - ra.keys()),
                lost=len(ra.keys() - rb.keys()),
                changed=len(changed),
                changed_row_commitment=crypto(
                    b"".join(sorted(bytes.fromhex(k) for k in changed))
                ),
                names=sorted(da[k][0] for k in changed) if len(changed) <= 25 else [],
                public_equal=ha["public"] == hb["public"],
                private_equal=ha["private"] == hb["private"],
                globals_equal=ha["global_hash"] == hb["global_hash"],
                expansions_equal=ea == eb,
                required_external_hash_changes=sorted(
                    key for key in xa if xa[key] != xb[key]
                ),
            )

        out[owner] = dict(
            edit=compare(*stages[:2]),
            clean=compare(*stages[1:]),
            bytes=[v[5] for v in stages],
            physical=[v[0]["full"] for v in stages],
            public=[v[0]["public"] for v in stages],
            missing_scope_public_rows=[v[-1] for v in stages],
        )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", type=Path)
    parser.add_argument("digest")
    parser.add_argument("out", type=Path)
    parser.add_argument("--rust-source", type=Path, required=True)
    p = parser.parse_args()
    with p.packet.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == p.digest
    available = (
        int(
            re.search(
                r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M
            )[1]
        )
        * 1024
    )
    assert (
        available > 8 * 2**30 + 380 * 2**20
        and shutil.disk_usage(p.out.parent).free > 15 * 2**30
    )
    sy, fields = rdr.schema(p.rust_source)
    report = {}
    with zipfile.ZipFile(p.packet) as z, tempfile.TemporaryDirectory(
        prefix="inline-adt-"
    ) as root:
        names = z.namelist()
        assert len(names) == len(set(names))
        worker = json.loads(z.read("worker.json"))
        assert worker["run"] == "41569845446" or int(worker["run"]) == 41569845446
        assert worker["head"] == "51f667c29b79a9a08010a04798e814d299877dff"
        kit = json.loads(z.read("scope-kit-inline.json"))
        sdk = json.loads(z.read("scope-sdks.json"))
        assert (
            kit["run"] == 41568934075
            and kit["head"] == "3a830cdc9f00b01c7110fac3653d8cd0b305c355"
        )
        for role in "PC":
            label = "inline-" + role
            data = json.loads(z.read(label + "/provenance.json"))
            assert (data["source"], data["driver"]) == KNOWN[role] and data == sdk[
                label
            ]
            folder = Path(root) / role
            folder.mkdir()
            checks = physical.verify(z, label + "/", folder)
            fx = json.loads(z.read("fixture-" + label + ".json"))
            assert fx["driver"] == data["driver"]
            tc = fx["exact_size_iterator"]
            assert (
                "E0277" in tc["withdrawn_impl"]
                and "E0271" in tc["changed_assoc_item"]
                and tc["old"]["stdout"] == "11\n"
                and tc["repaired"]["stdout"] == "19\n"
                and tc["old"]["full_elf_sha256"] != tc["repaired"]["full_elf_sha256"]
            )
            assert (
                "E0616" in fx["private"]
                and "E0004" in fx["opaque"]
                and "E0308" in fx["type_error"]
                and any(
                    "cannot be used on modules" in m
                    for m in fx["invalid_module_attribute"]
                )
            )
            for label2, state in fx["states"].items():
                assert all(
                    state["warm"][k] == state["fresh"][k]
                    for k in ("executables", "output", "rustdoc_json")
                )
            report[role] = dict(
                source=data,
                native=checks,
                metadata=load_owners(z, label, sy, fields),
                foreign_trait=tc,
                actual_rustdoc_and_scope_controls=sorted(fx["states"]),
            )
            p.out.write_text(
                json.dumps(
                    dict(zip_sha256=p.digest, run=worker, roles=report),
                    sort_keys=True,
                    indent=1,
                )
                + "\n"
            )
        print(
            [
                (
                    r,
                    report[r]["native"]["raw_rustc"],
                    [
                        (
                            o,
                            report[r]["metadata"][o]["edit"]["changed"],
                            report[r]["metadata"][o]["edit"]["public_equal"],
                        )
                        for o in OWNERS
                    ],
                )
                for r in "PC"
            ]
        )
        assert report["P"]["native"]["raw_rustc"] == sorted(OWNERS)
        prefix = "adt-rsic-upgrade/"
        load = lambda name: json.loads(z.read(prefix + name))
        agreement = lambda name, digest: crypto(z.read(prefix + name)) == digest
        term = load("terminal.json")
        assert (
            term["success"] is True
            and term["mode"] == "different-format"
            and agreement("registration.json", term["registration_sha256"])
        )
        reg = load("registration.json")
        assert (
            reg["factory_zip_sha256"]
            == "7164fae282a88ccab8f0cc7fde9a5adcd8d4a43ab14a90105b1639e2a627c86f"
            and reg["versions"]["P"] == reg["versions"]["C"]
        )
        for source, dest, oldfmt, newfmt in [
            ("P", "C", 24450, 49126),
            ("C", "P", 49126, 24450),
        ]:
            direction = source + "-to-" + dest
            folder = direction + "/"
            br = load(folder + "terminal.json")
            assert agreement(folder + "terminal.json", term["directions"][direction])
            assert (
                br["success"] is True
                and br["errors"] == {}
                and br["source_format"] == oldfmt
                and br["dest_format"] == newfmt
                and br["source"] == KNOWN[source][0]
                and br["dest"] == KNOWN[dest][0]
            )
            for phase, holder in [
                ("changed", "warm_sha256"),
                ("invalid", "warm_sha256"),
                ("repair", "warm_sha256"),
                ("changed", "independent_clean_sha256"),
                ("invalid", "independent_clean_sha256"),
                ("repair", "independent_clean_sha256"),
            ]:
                actual = (
                    folder
                    + ("" if holder == "warm_sha256" else "clean-")
                    + phase
                    + "/result.json"
                )
                assert agreement(actual, br[holder][phase])
                data = load(actual)
                if phase == "invalid":
                    assert data["diagnostics"] == ["E0308"]
                else:
                    assert data["diagnostics"] == [] and all(
                        re.fullmatch("[a-f0-9]{64}", x["sha256"])
                        for x in data["native"].values()
                    )
                    if holder == "warm_sha256" and phase == "changed":
                        assert data["previous_native_inodes_still_used"] == []
                    if holder == "independent_clean_sha256":
                        warm = load(folder + phase + "/result.json")
                        assert (
                            warm["output"] == data["output"]
                            and warm["executable_sha256"] == data["executable_sha256"]
                            and {k: v["sha256"] for k, v in warm["native"].items()}
                            == {k: v["sha256"] for k, v in data["native"].items()}
                        )
        p.out.write_text(
            json.dumps(
                dict(
                    zip_sha256=p.digest, run=worker, roles=report, format_crossover=term
                ),
                sort_keys=True,
                indent=1,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
