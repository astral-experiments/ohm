import json, sys
from pathlib import Path
import argparse, io, tarfile, hashlib

here = Path(__file__).resolve().parent
w = here.parent
sys.path.insert(0, str(w))
import scope_rdr as m

sys.path.insert(0, str(w / "indirect-check"))
import verify

parser = argparse.ArgumentParser(
    description="Reopen three prior graphs, edited metadata and native Cargo verdicts."
)
parser.add_argument("--rust-source", type=Path, required=True)
args = parser.parse_args()
sy, tables = m.schema(args.rust_source)
names = (w / "indirect-check/query-kinds.txt").read_text().splitlines()


def read_archive(path, expected):
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
        return {m.name: t.extractfile(m).read() for m in t if m.isfile()}


two = read_archive(
    w / "indirect-check/originals.tar.xz",
    "bb6b12f9c892b76c1fb1b694329d4c8cfe8d162cab06d311c5f5a7033c2d126f",
)
third = read_archive(
    here / "blanket.tar.xz",
    "47703c38e34095995326e38c120dc57d713d1fc82bcb1cebd1b4ad016d9002e1",
)


def decode(raw, crate):
    typed = {}
    h, defs, rows, exp, deps = m.decode(
        raw,
        sy,
        tables,
        crate,
        "rustc 1.99.0-dev (Ohm metadata 3)",
        typed=typed,
        selected_tables=["inherent_impls"],
    )
    r = m.Reader(raw, sy)
    r.pos = int.from_bytes(raw[8:16], "little")
    r.symbol()
    r.take(32)
    assert r.symbol() == crate and r.byte() == r.byte() == 0
    r.string()
    r.take(8)
    assert [r.var() for _ in range(7)] == [0, 0, 3, 0, 0, 0, 0]

    def array():
        count = r.var()
        if count:
            r.var()
        return count

    first = [array() for _ in range(13)]
    assert r.byte() == 1
    traits, incoh, alloc = [array() for _ in range(3)]
    return (
        h,
        defs,
        rows,
        dict(
            encoded_local_trait_slots=first[-1],
            trait_impl_groups=traits,
            incoherent=incoh,
            inherents=len(typed["selected_tables"]["inherent_impls"]),
        ),
    )


def inspect(raw, target):
    def read(stage, crate):
        return decode(raw[stage + "/" + crate + ".rmeta"], crate)

    o, n, cns = (
        read("original", "origin"),
        read("invalid", "origin"),
        read("original", "consumer"),
    )
    f0, f1 = read("original", "facade"), read("invalid", "facade")
    g, roots, edges = verify.graph_walk(raw["original/consumer-graph.bin"], names)
    targets = {}
    for t in target:
        (k,) = [k for k, v in o[1].items() if v[0] == t]
        valid = {o[0]["stable"] + k, k + o[0]["stable"]}
        r = sorted((i, e["kind"]) for i, e in g.items() if e["key"] in valid)
        targets[t] = r
    return dict(
        nodes=len(g),
        edges=edges,
        all_roots=roots,
        origin_global=[o[0]["global_hash"], n[0]["global_hash"]],
        facade_public=[f0[0]["public"], f1[0]["public"]],
        old_new_cohorts=[o[3], n[3]],
        old_query_nodes_for_origin_def=targets,
        changed_definitions=[n[1][k][0] for k in n[2] if o[2].get(k) != n[2][k]],
    )


def main():
    results = {}
    for case, targets in [
        ("constant", ["VALUE"]),
        ("glob", ["second", "first::VALUE"]),
        ("blanket", ["Candidate", "External", "Candidate::selected"]),
    ]:
        raw = (
            third
            if case == "blanket"
            else {
                n.removeprefix(case + "/"): b
                for n, b in two.items()
                if n.startswith(case + "/")
            }
        )
        for stage in [
            "original",
            "unchanged",
            "invalid",
            "clean-invalid",
            "repair",
            "clean-repair",
        ]:
            finish, dirty, errors = verify.recorded_events(raw[stage + "/stdout"])
            invalid = "invalid" in stage
            assert finish == [not invalid]
            assert errors == (
                [dict(constant="E0308", glob="E0659", blanket="E0034")[case]]
                if invalid
                else []
            )
            if stage == "unchanged":
                assert not dirty
            if stage.startswith("clean-"):
                matched = stage.removeprefix("clean-")
                for name in ["origin", "facade"] + ([] if invalid else ["consumer"]):
                    assert (
                        raw[stage + "/" + name + ".rmeta"]
                        == raw[matched + "/" + name + ".rmeta"]
                    )
        results[case] = inspect(raw, targets)
    assert json.loads(json.dumps(results)) == json.loads(
        (here / "query-controls.json").read_bytes()
    )
    print("accepted", [(k, v["nodes"], v["edges"]) for k, v in results.items()])


if __name__ == "__main__":
    main()
