"""Check the native build, provider, and migration readbacks from the original GNU jobs."""
import collections
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
def main():
    contents = (HERE / "source-observations.json.gz").read_bytes()
    index = json.loads((HERE / "originals.json").read_bytes())
    assert hashlib.sha256(contents).hexdigest() == index["readback_sha256"]
    records = json.loads(gzip.decompress(contents))
    assert set(records) == set(index["archives"]) and len(records) == 9
    for k, row in records.items():
        assert [row["archive"], row["zip"]] == index["archives"][k]
        assert row["run"] == 41109319369 and row["source"] == "6cb68d57fd6b5772f3c862027545bd2935e08ece"
    for role in ("signed","integrated"):
        across = {}
        for writer in ("register","syscall"):
            row = records[f"{writer}-{role}"]
            ident, phases = row["reader"], row["phases"]
            assert (ident["reader"],ident["writer"],ident["verified_sdk_members"]) == (role,writer,119)
            assert phases["invalid"]["e0425"]
            empty = phases["empty-new"]
            matched = ("image","text","verdicts")
            for step in ("edit","repeat","repair"):
                assert all(phases[step][k] == empty[k] for k in matched)
            assert phases["cold"]["image"] != empty["image"] and phases["cold"]["verdicts"]["starred"] == [["PLE0643",2]]
            assert empty["verdicts"] == {"starred": [], "bounds": [["PLE0643",1]], "valid":[]}
            across[writer] = [phases[k]["text"] for k in ("cold","edit","repeat")]
            print(writer,role,[(k,len(phases[k]["compiles"]),len(phases[k]["link_only"]),phases[k]["ruff_ld"])
                               for k in ("edit","repeat")])
        assert across["register"] == across["syscall"]
    for mode, n in (("aware",108),("migrate-classic",42),("migrate-signed",42)):
        record = records["provider-"+mode]["result"]
        assert record["total_Cargo"] == n == sum(len(h["phases"]) for h in record["histories"].values())
        for h in record["histories"].values():
            for row in h["phases"].values():
                assert row["actual_provider_ld"] >= 1
                assert row["source_specific_terminal"] == row["opening_trace"]
                if row["elf"] is not None:
                    assert row["elf"] in record["ELFs"] and row["cargo_exit"] == 0
        print(mode, n, "native Cargo builds")
    named = records["provider-named"]["result"]["cases"]
    assert set(named) == {"none","v1","v2","both"}
    for mode, rows in named.items():
        assert {row["image"] for row in rows.values()} == {rows["empty"]["image"]}
        assert bool(rows["repeat"]["rustcs"]) == (mode != "none")
    legacy = records["provider-legacy"]["result"]["cases"]
    mistakes, totals = collections.defaultdict(list), collections.Counter()
    for label, cases in legacy.items():
        role, policy, placement = label.split("-")
        for phase, row in cases.items():
            totals[role,policy] += 1
            assert row["empty_ld"] >= 1
            if row["empty"] != row["observed"] or not row["same_bytes"]:
                mistakes[role,policy].append((placement,phase))
    for policy,count in (("undeclared",8),("directories",4),("files",0)):
        assert all(totals[k,policy]==18 for k in ("aware","signed","classic"))
        assert not mistakes["classic",policy]
        assert sorted(mistakes["aware",policy]) == sorted(mistakes["signed",policy])
        assert len(mistakes["aware",policy]) == count
        print("Old writer",policy,"- stale warm/empty pairs out of 18:",count,"for released and integrated, 0 for #293")
    print("Four Ruff configurations and the two native writer protocols agree with the captured originals.")


if __name__ == "__main__":
    main()
