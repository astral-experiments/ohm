"""Prove the native outputs of independent clean compilers equivalent before counting."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile

import native_reference as n


def reference(root, role, revision):
    directory = root / f"clean-{revision}-{role}"
    output = json.loads(gzip.decompress((directory / "native.json.gz").read_bytes()))
    receipt = json.loads((directory / "visit.json").read_bytes())
    transcript = [json.loads(line) for line in gzip.decompress((directory / "cargo.stdout.gz").read_bytes()).splitlines()]
    n.need(transcript[-1] == {"reason": "build-finished", "success": True}
           and receipt["rev"] == revision and receipt["dirty"] == 375 and receipt["count"] is None
           and output["typed"] == "Expr=" + ("64" if revision == "A" else "56") + " valid=1 rejected"
           and receipt["whole"] == {key: output[key]["whole"] for key in ("cli", "reader")},
           "invalid independent clean reference")
    build, = [r for r in transcript if r["reason"] == "build-script-executed" and "#tikv-jemalloc-sys@" in r["package_id"]]
    return output, receipt["roster"], os.fsencode(str(Path(build["out_dir"]) / "build"))


def certify(root, raw=None):
    results = {}
    with tempfile.TemporaryDirectory(prefix="qualified-ruff-") as temporary:
        for rev in "AB":
            p, proster, old = reference(root, "P", rev)
            c, croster, new = reference(root, "C", rev)
            n.need(proster == croster and {k: v for k, v in p.items() if k != "cli"}
                   == {k: v for k, v in c.items() if k != "cli"}, "independent Ruff behavior or artifact inventories differ")
            files = []
            refs = {"P": p["cli"]["whole"], "C": c["cli"]["whole"]}
            for digest in refs.values():
                if raw is not None:
                    file = raw / digest
                else:
                    file = Path(temporary) / digest
                    if not file.exists():
                        with file.open("xb") as f:
                            subprocess.run(["zstd", "-dq", "-c", root / "reference-bodies" / (digest + ".zst")],
                                           check=True, stdout=f)
                n.need(n.hexdigest(file) == digest, "different physical native reference")
                files.append(file)
            proof = {"identical": True} if refs["P"] == refs["C"] else n.compare(*files, old, new)
            results[rev] = dict(refs=refs, reader=p["reader"]["whole"], roster=proster, proof=proof)
    return json.loads(json.dumps(results))
