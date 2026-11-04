"""Forecast the ordinary second edit from earlier full emissions in distinct QA histories."""

import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

PILOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PILOT))
import coordinator, release_scope
from component_epochs import gather

SPECS = (
    (
        23,
        41737649726,
        "b793f66dcaa3d935abca0fc2d5d9fd6de9737da7c3e3c1b05836581ffe481c7f",
    ),
    (
        24,
        41737656295,
        "cd34338da0ad5cb2812ac7f87baea7f93d97e49196ac448fb82cc0a7781d5505",
    ),
)


def case(arm, rid, sha):
    archive = Path(sys.argv[1 if arm == 23 else 2])
    with archive.open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == sha
    with ZipFile(archive) as z:

        def get(n):
            v = z.read(n)
            return gzip.decompress(v) if n.endswith(".gz") else v

        def j(n):
            return json.loads(get(n))

        allowed = set(json.loads((PILOT / "accepted-48.json").read_text()))
        spec = {r: v for r, v in release_scope.for_release(arm).items() if r in allowed}
        image = j("physical.json")["image_b3"]
        a = "C-reverse-old"
        b = "C-exec-edit"
        old = j(a + "/physical-decisions.json")["actors"]
        new = j(b + "/physical-decisions.json")["actors"]
        old_elf = j(a + "-receipt.json.gz")["published"]
        new_elf = j(b + "-receipt.json.gz")["published"]
        native = gather(z, "P-exec-edit")
        clock = native["native_roles"]
        assert native["all_unscaled_exact"] and len(old) == len(new) == len(spec) == 48

        def ready(stage, rec):
            buf = get(f"{stage}/actor-{rec['pid']}.tsv.gz").decode()
            (env,) = [
                x
                for x in buf.splitlines()
                if x.startswith('ENVKEY\t"CARGO_MAKEFLAGS"\t')
            ]
            pre = coordinator.before(buf, spec, image)
            assert pre["key"] == rec["key"] and pre["allowed"] == rec["allowed"]
            return pre, buf, env

        result = {}
        for r in sorted(allowed):
            old_pre, _, old_env = ready(a, old[r])
            new_pre, raw, new_env = ready(b, new[r])
            assert old_env != new_env and new[r]["response"] == "full"
            # Only a counterfactual. The real actors both do their complete full native link.
            same_fd_spelling = coordinator.before(
                raw.replace(new_env + "\n", old_env + "\n"), spec, image
            )
            assert same_fd_spelling["role"] == old_pre["role"] == r
            differences = [
                k
                for k, v in old_pre["parts"].items()
                if v != same_fd_spelling["parts"][k]
            ]
            qualified = bool(
                old[r].get("physical")
                and old_pre["allowed"]
                and same_fd_spelling["allowed"]
                and same_fd_spelling["key"] == old_pre["key"]
            )
            result[r] = {
                "would_match_with_original_jobserver_spelling": qualified,
                "old_had_donor": bool(old[r].get("physical")),
                "new_one_thread_and_closed": same_fd_spelling["allowed"],
                "different_typed_parts": differences,
                "groups_equal": old_pre["groups"] == same_fd_spelling["groups"],
                "old_output_sha256": old_elf[r],
                "new_output_sha256": new_elf[r],
                "signed_native_instructions": clock[Path(r).name + " StockWild"][
                    "instructions_raw"
                ],
            }
        hits = {
            r: v
            for r, v in result.items()
            if v["would_match_with_original_jobserver_spelling"]
        }
        wrong = {
            r
            for r, v in hits.items()
            if v["old_output_sha256"] != v["new_output_sha256"]
        }
        return {
            "run": rid,
            "zip_sha256": sha,
            "forecast_if_same_native_inputs_and_groups": sorted(hits),
            "signed_native_instructions_of_forecast": sum(
                v["signed_native_instructions"] for v in hits.values()
            ),
            "observed_different_full_elf_despite_this_forecast": sorted(wrong),
            "old_full_outputs": a,
            "new_full_outputs": b,
            "roles": result,
        }


if __name__ == "__main__":
    assert (
        len(sys.argv) == 3
    ), "supply the original release -23 and -24 ZIPs in that order"
    print(
        json.dumps(
            {
                "scope": "Conditional forecast on two earlier real full native links; no observed bypass or edited hardware speedup",
                "cases": {r: case(r, rid, h) for r, rid, h in SPECS},
            },
            indent=2,
            sort_keys=True,
        )
    )
