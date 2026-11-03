"""Replay the exact four-way typed admission and deny altered preimages before native dispatch."""

from pathlib import Path
import gzip, hashlib, json, sys, zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coordinator as c

P = HERE.parent / "workspace-link-proof"


def run(archive):
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        == "82148079f32d04d8d230d7a6c264c0a42407c038b61dc62e14b0d08095292eee"
    )
    allspec = json.loads((P / "roles.json").read_bytes())
    eligible = json.loads((HERE / "accepted-48.json").read_bytes())
    spec = {k: allspec[k] for k in eligible}
    history = {}
    negative = {}
    phases = ("old", "edit", "first-unchanged", "second-unchanged", "third-unchanged")
    with zipfile.ZipFile(archive) as z:
        for phase in phases:
            enrolled = json.loads(gzip.decompress(z.read(phase + "-native.json.gz")))
            reopened = {}
            for k, r in enrolled.items():
                text = gzip.decompress(z.read(phase + "/" + r["log"])).decode()
                if k not in spec:
                    try:
                        c.before(text, spec, r["image_b3"])
                    except ValueError:
                        continue
                    raise AssertionError("unregistered role admitted")
                d = c.before(text, spec, r["image_b3"])
                assert (
                    d["role"] == k
                    and d["parts"] == r["parts"]
                    and d["allowed"] == bool(r["typed_admitted"])
                )
                assert d["groups"] == [
                    list(map(int, x)) for x in c.rows(text)["ACTUAL-GROUP"]
                ]
                reopened[k] = d
                if k.endswith("/e2e-f5c6198f896cf7b0") and phase == "first-unchanged":
                    selected = next(
                        x for x in text.splitlines() if x.startswith("USED\t")
                    )
                    f = selected.split("\t")
                    f[3] = "0" * 64
                    try:
                        c.before(
                            text.replace(selected, "\t".join(f)), spec, r["image_b3"]
                        )
                    except AssertionError:
                        negative["mutable-consumed-byte"] = True
                    else:
                        raise AssertionError("unbound consumed bytes")
                    line = next(
                        x
                        for x in text.splitlines()
                        if x.startswith("OHMLOOK\tP\t") and x.split("\t")[-2] == "2"
                    )
                    altered = c.before(
                        text.replace(line + "\n", "", 1), spec, r["image_b3"]
                    )
                    assert altered["key"] != d["key"]
                    negative["omitted-ENOENT"] = True
                    bad = c.before(text, spec, "0" * 64)
                    assert not bad["allowed"]
                    negative["wrong-static-image"] = True
            assert len(reopened) == 48
            history[phase] = reopened
    potential = {
        cur: sorted(
            k
            for k, r in history[cur].items()
            if r["allowed"]
            and history[prev][k]["allowed"]
            and r["key"] == history[prev][k]["key"]
        )
        for prev, cur in zip(phases, phases[1:])
    }
    assert len(potential["edit"]) == 0 and len(potential["first-unchanged"]) == 48
    return {
        "native_originals": 240,
        "excluded_originals": 10,
        "negative": negative,
        "typed_pre_output_opportunities": {k: len(v) for k, v in potential.items()},
    }


if __name__ == "__main__":
    print(json.dumps(run(Path(sys.argv[1])), sort_keys=True, indent=2))
