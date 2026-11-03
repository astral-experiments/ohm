"""Reopen both real object names, the complete signed rejection trace and all 12 matched ledgers."""

import argparse, collections, gzip, hashlib, io, json, re, struct, sys, tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sip128 import sip
from core_rows import objects as core_defs


def sha(data):
    return hashlib.sha256(data).hexdigest()


def mangle(source):
    d = sip(source.encode() + b"\xff")
    n = int(d[16:] + d[:16], 16)
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + out
    return out.rjust(25, "0")


def cgu(row, sid):
    kr = row["definition_crate"]
    workspace = "ruff_workspace." + sid
    prefix = (
        workspace if kr == "ruff_workspace" else kr + "." + sid + "-in-" + workspace
    )
    name = mangle(prefix + "".join("-" + c for c in row["module"]) + row["suffix"])
    return (
        name
        if row["shard"] is None
        else mangle(name + "-ohm-split-" + str(row["shard"]))
    )


def sid(path):
    (val,) = re.findall(r"ruff_workspace-([a-z0-9]{13})/s-", path)
    return format(int(val, 36), "08x")


def read_graph(path, digest, indices, wanted):
    names = json.loads(
        (
            HERE.parent
            / "ruff-linter-check-attribution/evidence/field-visibility/preflight/signed22-query-kinds.json"
        ).read_bytes()
    )["names"]
    raw = (
        gzip.decompress(path.read_bytes())
        if path.suffix == ".gz"
        else path.read_bytes()
    )
    assert sha(raw) == digest and raw[:4] == b"RSIC" and raw[-13:] == b"rust-end-file"
    end = len(raw) - 13
    slots, nodes, expected = struct.unpack_from("<QQQ", raw, end - 24)
    pos = 7 + raw[6] + 8
    total = 0
    rows = []
    bits = (len(names) - 1).bit_length()

    def leb():
        nonlocal pos
        n = 0
        for shift in range(0, 64, 7):
            v = raw[pos]
            pos += 1
            n |= (v & 127) << shift
            if v < 128:
                return n
        raise ValueError("invalid LEB128")

    for _ in range(nodes):
        flags, idx = struct.unpack_from("<HI", raw, pos)
        kind = names[flags & ((1 << bits) - 1)]
        width = 1 + (flags >> bits & 3)
        n = (flags >> (bits + 2)) - 1
        key = "".join(f"{v:016x}" for v in struct.unpack_from("<QQ", raw, pos + 6))
        v = "".join(f"{v:016x}" for v in struct.unpack_from("<QQ", raw, pos + 22))
        pos += 38
        if n < 0:
            n = leb()
        if idx in indices or (kind, key) in wanted:
            rows.append(
                (
                    idx,
                    kind,
                    key,
                    v,
                    [
                        int.from_bytes(
                            raw[pos + j * width : pos + (j + 1) * width], "little"
                        )
                        for j in range(n)
                    ],
                )
            )
        pos += n * width
        total += n
    assert total == expected
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--signed-core", type=Path)
    p.add_argument("--rust-source", type=Path)
    p.add_argument("--old-graph", type=Path)
    p.add_argument("--new-graph", type=Path)
    a = p.parse_args()
    assert bool(a.old_graph) == bool(a.new_graph) and bool(a.signed_core) == bool(
        a.rust_source
    )
    r = json.loads((HERE / "receipt.json").read_bytes())
    raw = (HERE / "originals.tar.xz").read_bytes()
    assert sha(raw) == r["original_tar_sha256"]
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
        d = {m.name: t.extractfile(m).read() for m in t if m.isfile()}
        assert {n: sha(v) for n, v in d.items()} == r["original_member_sha256"]
    get = lambda key: json.loads(d[key])
    prior = get("signed-prior.json")["sessions"]
    assert len(prior) == 1
    s = sid(prior[0]["path"])
    assert s == r["stable_ids"]["signed"]
    root = get("signed-trace.json")
    nine = {
        k
        for k, v in get("signed-direct.json")["cgus"].items()
        if v["reason"] == "unforceable"
        and not v["changes"]
        and not v["absent"]
        and not v["ambiguous"]
    }
    assert len(nine) == 9
    labels = r["labels"]
    assert (
        len({v["signed"] for v in labels}) == len({v["actual"] for v in labels}) == 122
    )
    assert all(cgu(row, s) == row["signed"] for row in labels)
    assert nine == {v["signed"] for v in labels if v["signed_nine"]}
    for rank in range(6):
        for role, selected in [("P", "parent"), ("C", "candidate")]:
            obs = get(f"rank-{rank}/objects-{role}.json")["ruff_workspace"]
            c = sid(obs["current"])
            assert c == sid(obs["prior"]) == r["stable_ids"]["actual"]
            ledger = {k.removesuffix(".o"): v for k, v in obs["objects"].items()}
            assert len(ledger) == 124
            modes = {}
            for fn, v in ledger.items():
                same = v["previous"][:2] == v["current"][:2]
                assert same == v["same_inode"]
                if same:
                    assert v["before_sha256"] == v["after_sha256"]
                modes[fn] = (
                    "donor"
                    if same
                    else "regenerated_identical"
                    if v["before_sha256"] == v["after_sha256"]
                    else "changed"
                )
            assert dict(collections.Counter(modes.values())) == r["whole_family"][role]
            for row in labels:
                assert (
                    cgu(row, c) == row["actual"]
                    and modes[row["actual"]] == row[selected]
                )
            assert set(modes) - {v["actual"] for v in labels} == set(
                r["unjoined"]["actual"]
            )
            if role == "C":
                assert all(modes[n] == "donor" for n in r["unjoined"]["actual"])
                obj = ledger["bkqk9vgkyoct0gf3jem7b0j8g"]
                assert (
                    obj["current"][2] == 1734056
                    and obj["before_sha256"]
                    == obj["after_sha256"]
                    == "91013f00d7c733dd09f7ecf9da0c9fb4132a97a3bc8bb3c182c968361436311e"
                )
    wk = get("signed-prices.json")
    owner = "ruff_workspace/lib"
    unit = "1ik705odb0wi7ez86mr5nie6x"
    assert (
        wk["all_samples"] == r["weights"]["all_samples"]
        and wk["period"] == r["weights"]["period"]
        and wk["modules"][owner][unit] == r["weights"]["unit"]
    )
    assert (
        wk["whole"] == r["weights"]["whole"]
        and get("signed-join.json")["owners"]["ruff_workspace"]["old_owner_hardware"]
        == r["weights"]["owner"]
    )
    decisions = root["decisions"]
    (item,) = [d for d in decisions if d["cgu"] == unit]
    trace = r["trace"]
    trait = trace[-1]
    assert item["direct_failure"]["path"] == trace[:2] and any(
        v["path"] == trace for v in item["observed_rejections"]
    )
    assert trait["previous_value"] != trait["current_value"] and all(
        v["previous_value"] == v["current_value"] for v in trace[:4]
    )
    subjects = [v for v in decisions if v["actual_cgu_reuse"] == "No"]
    assert len(subjects) == 49

    def rejection(v):
        return v["direct_failure"]["path"][-1]["name"]

    assert {v["cgu"]: rejection(v) for v in subjects} == r["signed_cgu_direct"] and [
        v["cgu"] for v in subjects if rejection(v) == "layout_of"
    ] == [unit]
    touched = {
        v["cgu"]
        for v in subjects
        if any(
            t["path"][-1]["name"] == "trait_impls_of"
            and t["path"][-1]["key"] == trait["key"]
            for t in v["observed_rejections"]
        )
    }
    assert (
        touched == set(r["signed_IntoIterator_observed_rejected"]) and len(touched) == 8
    )
    refs = {(v["kind"], v["key"]): v for v in r["trait_children"]}
    assert len(refs) == r["trait_children_count"] == 306
    cohort = {
        v["key"] for v in r["trait_children"] if v["kind"] == "implementations_of_trait"
    }
    target = r["changed_trait_input"][0]
    assert len(cohort) == 57 and target["kind"] == "implementations_of_trait"
    lookup = {}
    for nm, role in wk["roles"].items():
        inp = struct.pack(
            "<QQQ",
            int(role["physical_group"][-1], 36),
            int(trait["key"][:16], 16),
            int(trait["key"][16:], 16),
        )
        key = sip(inp)
        if key in cohort:
            lookup[nm] = key
    assert len(lookup) == 8 and lookup["ruff_python_ast/lib"] == target["key"]
    if a.signed_core:
        assert sha(a.signed_core.read_bytes()) == r["core_sha256"]
        actual = core_defs(a.signed_core, a.rust_source, r["core_definition_paths"])
        assert json.loads(json.dumps(actual)) == r["core_definition_paths"]
    if a.old_graph:
        old = read_graph(
            a.old_graph,
            "c61bb34d8fba3f5cff19de4475340179d783adc976455ea3fe94d92356bf0c77",
            {v["idx"] for v in refs.values()} | {v["previous_index"] for v in trace},
            set(),
        )
        old = {ix: (kind, key, val, edges) for ix, kind, key, val, edges in old}
        for i, v in enumerate(trace):
            kind, key, val, edges = old[v["previous_index"]]
            assert (kind, key, val) == (v["name"], v["key"], v["previous_value"])
            if i + 1 < len(trace):
                assert (
                    edges[trace[i + 1]["ordinal_from_parent_0"]]
                    == trace[i + 1]["previous_index"]
                )
        assert old[trait["previous_index"]][3] == [
            v["idx"] for v in r["trait_children"]
        ]
        for v in refs.values():
            assert old[v["idx"]][:3] == (v["kind"], v["key"], v["value"])
        new = read_graph(
            a.new_graph,
            "54c33c1062b889240d8f118dae43c4a40da51f5f9732b4381b2c5c51e0f30bce",
            set(),
            set(refs),
        )
        fresh = collections.defaultdict(list)
        for ix, k, key, v, _ in new:
            fresh[(k, key)].append([ix, v])
        changed = [
            {**v, "current": fresh[k]}
            for k, v in refs.items()
            if len(fresh[k]) != 1 or fresh[k][0][1] != v["value"]
        ]
        assert changed == r["changed_trait_input"]
    print(
        "Accepted 12 native ledgers, 122 canonical identities, all 9 disputed units and the signed user-instruction accounting."
    )


if __name__ == "__main__":
    main()
