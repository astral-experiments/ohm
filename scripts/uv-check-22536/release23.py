"""Release-specific admission over the unchanged physical #22536 check."""
from pathlib import Path
import gzip
import hashlib
import json
import re

H = Path(__file__).resolve().parent
REGISTRATION = "fa8da30c4f541c3ee359e663f01556732d5e9d895a66ed05a9b52698f7fc5cdc"


def read(p):
    return json.loads(Path(p).read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def lock():
    if not __debug__:
        raise RuntimeError("optimizing away native admission assertions is unsupported")
    if not (H / "release23-inputs.json").is_file():
        raise RuntimeError("Disabled: requires authenticated official -23 and completed #22958 production SDK intake")
    assert sha((H / "registration.json").read_bytes()) == REGISTRATION
    data = read(H / "release23-inputs.json")
    assert data["registration"] == REGISTRATION
    assert data["signed_cargo"] == data["roles"]["R"]["runtime"]["bin/cargo"]["sha256"]
    return data


def canonical(record, role, sources, source_blobs):
    """Derive the actual linked five-visit outcome from its commands and native stdout."""
    assert record["source_blobs"] == source_blobs
    assert record["source_commit"] == sources[role]["source"]["commit"]
    assert record["rustc_launcher_sha256"] == sources[role]["runtime"]["bin/rustc"]["sha256"]
    names = ("A-cold", "B-first-warm", "B-independent-cold", "C-first-warm", "C-independent-cold")
    outputs = ("Or Or true 17\n", "LShift Or true 17\n", "LShift Or true 17\n",
               "LShift Or false 17\n", "LShift Or false 17\n")
    statuses = ("not-loaded", "loaded", "not-loaded", "loaded", "not-loaded")
    assert set(record["visits"]) == set(names)
    hashes = []
    for name, output, status in zip(names, outputs, statuses, strict=True):
        visit = record["visits"][name]
        built, linked, executed, listed = visit["commands"]
        assert all(cmd["exit"] == 0 for cmd in visit["commands"])
        assert "-Zassert-incr-state=" + status in built["argv"]
        assert linked["argv"][1:] == ["main.rs", "--extern", "dep=libdep.rlib"]
        assert Path(executed["argv"][0]).name == "main" and executed["out"] == output
        assert listed["argv"][1:] == ["-Zls=public_hash", "libdep.rlib"]
        assert listed["out"] == visit["public_hash"] and listed["out"].strip()
        hashes.append(listed["out"])
    a, warm, cold, changed, fresh = hashes
    fields = dict(A_differs_from_B=a != cold, B_warm_equals_cold=warm == cold,
                  C_warm_equals_cold=changed == fresh, pointer_switch_changes_public_hash=cold != changed)
    assert record["checks"] == fields and record["matches_official_regression"] is all(fields.values())
    assert all(v for k, v in fields.items() if k != "B_warm_equals_cold")
    if role != "R":
        assert all(fields.values()), "corrected/full canonical fixture failed"
    return "passed" if fields["B_warm_equals_cold"] else "only-B-failed"


def terminal(sidecars, workspace_file, header_lines, cas):
    """Bind one physically emitted sidecar to this exact metadata output and its two real headers."""
    path = Path(workspace_file)
    assert re.fullmatch(r"libuv_client-[0-9a-f]{16}\.rmeta", path.name) and path.parent.name == "out"
    expected = str(path.parent.parent / "fingerprint" / "lib-uv_client.public-api-hash")
    warm, cold = sidecars
    assert warm.keys() == cold.keys()
    if {p for p in warm if warm[p] != cold[p]} != {expected}:
        return None
    pair = []
    for side, lines in zip(sidecars, header_lines, strict=True):
        digest = side[expected]
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        payload = gzip.decompress((cas / (digest + ".gz")).read_bytes())
        assert sha(payload) == digest
        m = [s.split(" ", 1)[1] for s in lines if re.fullmatch(r"public_hash [0-9a-f]{32}", s)]
        if len(m) != 1 or json.loads(payload) != {"version": 1, "value": m[0]}:
            return None
        pair.append({"public_hash": m[0], "sidecar_sha256": digest, "sidecar_hex": payload.hex()})
    if pair[0]["public_hash"] == pair[1]["public_hash"]:
        return None
    return {"path": expected, "directed": pair}


def ctfe_states(folder):
    """Re-read the complete native three-state relation, including the exact directed failure."""
    result = {}
    for phase in "BCD":
        p = folder / ("fresh-" + phase) / "typed-warm-cold.json.gz"
        t = json.loads(gzip.decompress(p.read_bytes()))
        if t["accepted"]:
            assert not t["ctfe_terminal_only"] and not t["changed_sidecars"] and not t["unresolved"]
            continue
        assert t["ctfe_terminal_only"] and not t["unresolved"]
        row = t["terminal_ctfe_evidence"]
        assert t["changed_sidecars"] == [row["path"]]
        native = t["changes"]["uv_client"]["typed"]["checks"]
        assert all(v for k, v in native.items() if k != "native_crate_root") and not native["native_crate_root"]
        result[phase] = row
    return result


def repeated(first, second, canonical_stock):
    assert canonical_stock == "only-B-failed"
    seeds = [sha((p / "cold-A/kernel.json.gz").read_bytes()) for p in (first, second)]
    assert len(set(seeds)) == 2, "reused stock A instead of a second independent history"
    a, b = map(ctfe_states, (first, second))
    assert a and a == b, "different #22536 CTFE failure in the two original histories"
    return {"directed_failures": a, "independent_cold_kernel_sha256": seeds}


def publication(record, signed):
    asset, = [entry for entry in record["assets"] if entry["id"] == signed["asset"]["id"]]
    assert asset["size"] == signed["asset"]["size"] and asset["digest"] == "sha256:" + signed["sha256"]
    assert type(record["id"]) is int and record["id"] == signed["release_id"]
    assert record["tag_name"] == signed["tag"] == "ohm-1.99.0-23"
    assert record["target_commitish"] == signed["coordinator"]
    assert record["immutable"] is True and record["draft"] is False and record["prerelease"] is False
    assert isinstance(record["published_at"], str) and record["published_at"]
    return {k: record[k] for k in ("id","tag_name","target_commitish","immutable","draft","prerelease","published_at")}


def publication_pair(root, expected):
    before = publication(read(root / "fresh-publication.json"), expected)
    after = publication(read(root / "fresh-publication-after.json"), expected)
    assert before == after
    return before


def canonical_sources(folder):
    rows = read(folder / "kit/ctfe/captured.json")["prs"]["318"]["paths"]
    return {Path(path).name: row["sha"] for path, row in rows.items()}


def confirm_native(root, here, inputs):
    gate = root / "qualification"
    selection = read(gate / "accepted.json")
    assert selection["control"] in ("R", "S") and selection["treatment"] == "F"
    first = ctfe_states(gate / "signed-1")
    canonical_stock = canonical(read(gate / "actual-ctfe-R.json"), "R", inputs["roles"], canonical_sources(here))
    canonical(read(gate / "actual-ctfe-F.json"), "F", inputs["roles"], canonical_sources(here))
    assert not ctfe_states(gate / "treatment")
    if first:
        assert selection["control"] == "S" and inputs["full_variant"] == "full_with_ctfe" and "S" in inputs["roles"]
        assert not ctfe_states(gate / "corrected")
        canonical(read(gate / "actual-ctfe-S.json"), "S", inputs["roles"], canonical_sources(here))
        assert repeated(gate / "signed-1", gate / "signed-2", canonical_stock) == selection["replicated_ctfe"]
    else:
        assert selection["control"] == "R" and selection["replicated_ctfe"] is None
    return {"release": inputs["release"]["tag"], "control": selection["control"],
            "full_variant": inputs["full_variant"], "canonical_signed": canonical_stock}
