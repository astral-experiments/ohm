"""Verify two physical Rust owners and the separately refused native ELF equality."""

import ast
import gzip
import hashlib
import json
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NATIVE = "6a2f3a27447c6a9ca6c4edb5d93b7c8f3405b23b7f6ba032a83be2265df0acc9"
DRIVER = "45345893362d95f8343e3f366dffcc663d2e105b8ee27bea8c16fe248665f51d"
CARGO = "0617e34321cf33fcce38904d066f0d4981b79f752896d37b97d1aed1fbddc48f"
HARD = b"/dev/null/ohm-untracked-relink-inputs"
RAW = "2d067c7a3a254b6e840c1937512c335b4df8cbbcbc3c4763becc12ae934a94a5"
h = lambda b: hashlib.sha256(b).hexdigest()


def main():
    native = HERE / "native-owner.zip"
    assert h(native.read_bytes()) == NATIVE
    with zipfile.ZipFile(native) as z, zipfile.ZipFile(HERE / "prior-native.zip") as prior:
        read = lambda n: z.read("native-owner/" + n)
        obj = lambda n: json.loads(read(n))
        sdk = obj("sdk.json")
        assert sdk["driver"] == DRIVER and sdk["cargo"] == CARGO
        ker = obj("kernel.json")
        tasks = {}
        for owner in ker["rustcs"]:
            log = gzip.decompress(read("observed/trace." + str(owner["pid"]) + ".gz")).decode()
            execs = re.findall(r'^execve\(("(?:[^"\\]|\\.)*"), (\[.*?\]), .*\) = 0$', log, re.M)
            (argv,) = [ast.literal_eval(args) for exe, args in execs if ast.literal_eval(exe) == owner["exe"]]
            assert argv == owner["argv"] and argv[argv.index("--crate-name") + 1] == owner["crate"]
            assert owner["driver"] == DRIVER and all(m in log for m in owner["maps"])
            assert any("PROT_EXEC" in m and "librustc_driver-" in m for m in owner["maps"])
            tasks[owner["crate"]] = argv
        assert len(ker["rustcs"]) == 34 and len({v["pid"] for v in ker["rustcs"]}) == 34
        p = tasks["portable_atomic"]
        assert any(v.endswith("/portable-atomic-1.11.0/src/lib.rs") for v in p)
        assert all(
            v in p
            for v in (
                'feature="default"',
                'feature="fallback"',
                "--emit=dep-info,metadata,link",
                "-Zohm-check-relink-inputs",
            )
        )
        assert any(
            v.startswith("portable_atomic=") and v.endswith("/libportable_atomic-32f41f9e0ba0c147.rmeta")
            for v in tasks["salsa"]
        )
        sampled = obj("untraced-processes.json")
        assert sorted(q["crate"] for q in sampled.values()) == ["portable_atomic", "salsa"]
        for pid, q in sampled.items():
            assert q["driver"] == DRIVER and any("r-xp" in s and "librustc_driver" in s for s in q["driver_mapping"])
            assert q["argv"][1:] == tasks[q["crate"]][1:]
            last = q["cargo_ancestry"][-1]
            assert last["exe"].endswith("/sdk/bin/cargo") and "build" in last["argv"] and "ruff" in last["argv"]
        old_rows = [json.loads(l) for l in prior.read("C/native-buggy/stdout").splitlines()]
        (old_r,) = [
            r
            for r in old_rows
            if r.get("reason") == "compiler-artifact" and r["target"]["name"] == "portable_atomic"
        ]
        (old_shard,) = {
            re.search(r"/registries/(v2-\w+)/portable-atomic/", v)[1].encode() for v in old_r["filenames"]
        }
        previous = json.loads(gzip.decompress(prior.read("C/registry-prefix/external-members.json.gz")))
        (k,) = [
            k for k in previous if old_shard.decode() in k and "/32f41f9e0ba0c147/" in k and k.endswith(".d")
        ]
        assert previous[k][-2:] == [12981, RAW]
        for name in ("seed", "before-first", "after-first", "after-repeat"):
            record = obj(name + "/physical.json")
            d = read(name + "/portable_atomic/rustc.d")
            (shard,) = {m.group(1) for m in re.finditer(rb"/registries/(v2-\w+)/portable-atomic/", d)}
            assert (
                len(d) == 12981
                and d.count(shard) == d.count(HARD) == 3
                and h(d.replace(shard, old_shard)) == RAW
            )
            for who, length, expected in (
                ("portable_atomic", 57, "cf8779a01c47500b0742e1e53824c4408b3dd680d5d19bf04d9bdf6d8fd1e521"),
                ("salsa", 14, "fd037d91f7fc9eface8316b71b539f18d45f3a4fe8b7d18bf4676d80599047c0"),
            ):
                b = read(name + "/" + who + "/cargo.bin")
                assert len(b) == length and h(b) == expected and (HARD in b) == (who == "portable_atomic")
                assert h(read(name + "/" + who + "/rustc.d")) == record[who]["dep_info"]["sha256"]
        cli = obj("outcome.json")["native"]
        assert (
            len(cli) == 3
            and len({x["bytes"] for x in cli}) == 1
            and cli[0]["sha256"] != cli[1]["sha256"] == cli[2]["sha256"]
        )
        assert cli[0]["runtime"] == cli[1]["runtime"] == cli[2]["runtime"]
        for record in cli[0]["runtime"].values():
            assert [m["code"] for m in json.loads(record["stdout"])] == ["RUF009"] * record["exit"]
        return dict(
            raw_old_dep_info=RAW,
            old_output_shard=old_shard.decode(),
            new_output_shard=shard.decode(),
            selected_traced={
                k: next(x["pid"] for x in ker["rustcs"] if x["crate"] == k)
                for k in ("portable_atomic", "salsa")
            },
            selected_untraced={v["crate"]: int(k) for k, v in sampled.items()},
            true_rustcs=len(ker["rustcs"]),
            original_elf_gate=False,
            native_hashes=[x["sha256"] for x in cli],
            native_bytes=cli[0]["bytes"],
            runtime_verdicts=12,
            scored_pairs=0,
        )


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True, indent=2))
