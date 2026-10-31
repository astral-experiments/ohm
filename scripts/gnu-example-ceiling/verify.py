"""Recompute both ceilings and their sensitivity from the two separately downloaded packets."""

import argparse, gzip, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit, pmu, study, topology, workload as w


def load(p):
    return json.loads(p.read_bytes())


def host(root):
    e = load(root / "enrollment.json")
    assert (
        e["plan"] == kit.ROLES["plan_sha256"] and e["order"] == kit.ROLES["orders"][e["position"]]
    )
    assert not (root / "refused.txt").exists()
    pmu.calibration(root / "observers", root, replay=True)
    cust = load(root / "custody/cargo.json")
    assert (
        cust["source"] == kit.TOOLCARGO
        and cust["source_tree"] == "bf643fa158734642bfee4a2aa8eff4d98bd8a09c"
        and cust["archive_features"] == "ohm-defaults,all-static"
    )
    cap = load(root / "custody/signed.json")
    assert (
        cap["release"]["assets"][0]["sha256"] == load(HERE / "signed-members.json")["sha256"]
        and len(cap["members"]) == 3768
    )
    rebuilt = {}
    boots = load(root / "host.json")["raw_system"]["/proc/sys/kernel/random/boot_id"]
    assert boots and len(boots) == 36
    activations = []
    for mode in e["order"]:
        d = root / mode
        v = load(d / "accepted.json")
        sel = load(d / "selected.json")
        ids = load(d / "identities.json")
        tg = Path(ids["environment"]["CARGO_TARGET_DIR"])
        activate = load(root / (mode + "-activation.json"))
        activations.append(activate)
        assert activate["files"] >= 3768
        for n in ("old", "edit", "repeat", "settled", "empty"):
            meta = load(d / n / "invocation.json")
            assert meta["argv"] == w.CLI and meta["status"] == 0
            a = w.plain_artifacts(gzip.decompress((d / n / "stdout.gz").read_bytes()))
            if n in ("edit", "repeat", "settled"):
                actual = topology.read(
                    d / n / "trace",
                    sel,
                    "topology" if n == "settled" else mode,
                    names=w.NAMES,
                    registry_target=tg,
                )
                if n == "settled":
                    assert actual == v["settled"] and a["units"] == v["repeat"]["typed"]
                else:
                    assert v[n]["native"] == actual and v[n]["typed"] == a["units"]
                    # The JSON writer sorts maps. Restore the observed kernel exec
                    # order before comparing the original ordered per-example rows.
                    v[n]["native"] = actual
        for phase in ("returned", "settled-programs", "empty-programs", "old-programs"):
            expected = v["old_programs"] if phase == "old-programs" else v["programs"]
            products = load(d / phase / "12-images.json")
            assert products == expected and set(products) == w.NAMES
            for k, (_digest, size, std, err) in products.items():
                assert (
                    size > 0
                    and len(_digest) == 64
                    and kit.H(gzip.decompress((d / phase / (k + "-out.gz")).read_bytes())) == std
                    and kit.H(gzip.decompress((d / phase / (k + "-err.gz")).read_bytes())) == err
                )
        for x, (phase, bad) in enumerate([("old-case", True), ("fixed-case", False)]):
            out, err = [
                gzip.decompress((d / phase / "case" / (n + ".gz")).read_bytes())
                for n in ("stdout", "stderr")
            ]
            assert (
                (b"panicked" in err) == bad
                and b"1 passed; 0 failed" in out
                and [kit.H(out), kit.H(err)] == [v["cases"][x]["stdout"], v["cases"][x]["stderr"]]
            )
        rebuilt[mode] = v
    assert (
        activations[0]["SDK_inode"] != activations[1]["SDK_inode"]
        and activations[0]["operational_tools"] == activations[1]["operational_tools"]
    )
    result = study.qualify(rebuilt["tree"], rebuilt["plain"])
    assert result == load(root / "qualified.json")
    return {"enrollment": e, "boot": boots, "bounds": {k: v["ceiling"] for k, v in result.items()}}


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("receipts", nargs="+", type=Path)
    paths = a.parse_args().receipts
    assert len(paths) in (1, 2)
    r = [host(p) for p in paths]
    if len(r) == 2:
        assert (
            {x["enrollment"]["position"] for x in r} == {"01", "02"}
            and len({x["boot"] for x in r}) == 2
            and len({x["enrollment"]["run"] for x in r}) == 1
            and len({x["enrollment"]["head"] for x in r}) == 1
        )
    verdict = "requires two independent complete workers"
    if len(r) == 2:
        repeat = [x["bounds"]["repeat"] for x in r]
        if all(v["ideal_high"] < 2 for v in repeat):
            verdict = "reject a frontend-only 2x on this registered repeat"
        elif all(v["ideal_low"] > 2 for v in repeat):
            verdict = "frontend-only design may clear 2x before real product overhead"
        else:
            verdict = "the measured ceilings leave the 2x decision unresolved"
    print(json.dumps({"workers": r, "decision": verdict}, indent=2, sort_keys=True))
