"""Read the 24 old/new ty_python_semantic file-size pairs from each prior package-profile migration."""

from pathlib import Path
import gzip
import io
import json
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import signed_readers as h


def compare(data):
    rows = []
    for i in range(1, 13):
        root = data / f"one-package-{i:02d}"
        meta = h.read(root.with_suffix(".json").read_bytes())
        path = root.with_suffix(".zip")
        raw = path.read_bytes()
        assert (
            meta["workflow_run"]["id"] == 41154300915
            and meta["workflow_run"]["head_sha"] == "3c9c82bb960564dbe3b0df7c0a736662354e502d"
            and meta["digest"] == "sha256:" + h.sha(raw)
            and meta["size_in_bytes"] == len(raw)
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as z, tarfile.open(
            fileobj=io.BytesIO(z.read(z.namelist()[0])), mode="r:gz"
        ) as t:
            for arm in ("0", "1"):

                def amount(visit, name):
                    blob = t.extractfile(
                        "./opt" + arm + "/" + visit + "/allocated-ledger.gz"
                    ).read()
                    return {
                        (r[1], r[2]): (r[0], r[5])
                        for r in h.read(gzip.decompress(blob))
                        if "/ty_python_semantic-" in r[0] and Path(r[0]).name == name
                    }

                for name in ("ohm-check-dep-graph.bin", "query-cache.bin"):
                    old = amount("first-unchanged", name)
                    new = amount("switch-unchanged", name)
                    assert len(old) == 1 and len(new) == 2
                    (first,) = old.keys()
                    (other,) = new.keys() - old.keys()
                    assert new[first] == old[first]
                    rows.append([path.name, arm, name, old[first][1], new[other][1]])
    assert len(rows) == 48 and all(q[3] != q[4] for q in rows)
    return rows


if __name__ == "__main__":
    print(json.dumps(compare(Path(sys.argv[1])), indent=2))
