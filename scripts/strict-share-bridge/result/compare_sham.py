"""Compare the bridge's forwarding baseline with the prior unwrapped study's archived physical invocations."""

from collections import Counter
from pathlib import Path
import gzip
import io
import json
import os
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reopen as r

PLAIN_HEAD = "3c9c82bb960564dbe3b0df7c0a736662354e502d"
PLAIN_RUN = 41154300915


def identify(bs, arm):
    sub = r.J(bs["subjects.json"])
    assert sub["source"] == r.h.SOURCES and sub["history"] == r.h.PATCH
    assert r.J(bs["strict.json"])["cargo"] == r.h.FIXED
    rid = sub["tools"]["rustc"]["dev_ino"]
    stage_sources = Counter()
    incrementals = full = shared = 0
    base = arm + "/empty-edited/kernel"
    for row in bs[base + "/exec.tsv"].decode().splitlines():
        idx, _, d, i, _, _ = row.split("\t")
        argv = [os.fsdecode(v) for v in bs[base + "/args-" + idx.zfill(4)][:-1].split(b"\0")]
        if (
            [int(d), int(i)] != rid
            or "--crate-name" not in argv
            or "--out-dir" not in argv
            or any(x.startswith("--print") for x in argv)
        ):
            continue
        full += 1
        flags = [argv[i + 1] for i, t in enumerate(argv) if t == "-C"] + [
            t[2:] for t in argv if t.startswith("-C") and len(t) > 2
        ]
        incrementals += any(x.startswith("incremental=") for x in flags)
        if "-Zohm-shared-stages" in argv:
            source = next((x for x in argv if x.endswith(".rs")), "<stdin>")
            shared += 1
            stage_sources[source] += 1
    base = arm + "/first-unchanged"
    v = r.J(bs[base + "/visit.json"])
    total = r.h.disk(bs, base, v["storage"])
    reg = r.region(r.J(gzip.decompress(bs[base + "/allocated-ledger.gz"])))
    assert total == sum(reg.values()) and full == 304 and incrementals == 35
    return {
        "full": full,
        "incremental_flag": incrementals,
        "all_shared_stages": shared,
        "workspace_shared_stages": sum(
            n for p, n in stage_sources.items() if p.startswith("crates/")
        ),
        "repeat_allocated_B": total,
        "repeat_regions_B": reg,
    }, stage_sources


def main(plain, wrapped):
    out = []
    for id in ("01", "02"):
        p = plain / ("one-package-" + id)
        meta = r.J(p.with_suffix(".json").read_bytes())
        raw = p.with_suffix(".zip").read_bytes()
        assert (
            meta["workflow_run"]["id"] == PLAIN_RUN
            and meta["workflow_run"]["head_sha"] == PLAIN_HEAD
        )
        assert meta["size_in_bytes"] == len(raw) and meta["digest"] == "sha256:" + r.h.sha(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert z.namelist() == ["one-package-" + id + ".tar.gz"]
            a, sources1 = identify(r.h.unpack(z.read(z.namelist()[0])), "opt0")
        q = wrapped / ("share-bridge-" + id)
        here = r.J(q.with_suffix(".json").read_bytes())
        b, sources2 = identify(r.open_archive(q.with_suffix(".zip").read_bytes(), here, id), "optA")
        assert a["all_shared_stages"] == 254 and b["all_shared_stages"] == 223
        assert a["workspace_shared_stages"] == 31 and b["workspace_shared_stages"] == 0
        old = {k: v for k, v in sources1.items() if not k.startswith("crates/")}
        assert old == dict(sources2)
        out.append(
            {
                "row": id,
                "prior_unwrapped_artifact": meta,
                "current_sham_artifact": here,
                "unwrapped": a,
                "sham": b,
                "changed_shared_stage_workspace_sources": {
                    k: v for k, v in sources1.items() if k.startswith("crates/")
                },
            }
        )
    return out


if __name__ == "__main__":
    assert len(sys.argv) == 3, "compare_sham.py prior-one-package/result bridge/result"
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True, indent=2))
