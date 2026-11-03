"""Independently derive each role decision directly from the archived full resolver and Cargo witnesses."""

from pathlib import Path
from zipfile import ZipFile
import collections, gzip, hashlib, json, sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import certificate


def open_result(archive, archive_sha, run, head):
    with archive.open("rb") as src:
        assert hashlib.file_digest(src, "sha256").hexdigest() == archive_sha
    specs = json.loads((HERE / "roles.json").read_bytes())
    assert len(specs) == 50
    with ZipFile(archive) as z:
        assert len(set(z.namelist())) == len(z.namelist()) and z.testzip() is None

        def raw(name):
            return (
                gzip.decompress(z.read(name)) if name.endswith(".gz") else z.read(name)
            )

        def row(name):
            return json.loads(raw(name))

        adm = row("admission.json")
        assert (
            adm["head"] == head
            and str(adm["run"]) == str(run)
            and not adm["bypass_compiled"]
        )
        pin = json.loads((HERE / "source-preflight.json").read_bytes())
        assert adm["registration"] == pin
        if "actor.json" not in z.namelist():
            diagnostics = {
                name: hashlib.sha256(raw(name)).hexdigest()
                for name in ("source.err", "source.out")
                if name in z.namelist()
            }
            return {
                "complete": False,
                "run": run,
                "head": head,
                "original_sha256": archive_sha,
                "admission": adm,
                "stop": "no built source actor",
                "diagnostic_sha256": diagnostics,
            }
        assert row("actor.json")["source"] == pin["after"]
        signed = {}
        history = {}
        physical = (
            row("physical-images.json")
            if "physical-images.json" in z.namelist()
            else {}
        )
        if physical:
            act = row("actor.json")
            assert (
                physical["source_static_sha256"] == act["actor"]
                and physical["stock_sha256"]
                == act["stock"]
                == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
                and physical["llvm_sha256"] == act["llvm"]
            )
        all_names = set(z.namelist())
        for tag in (
            "old",
            "edit",
            "first-unchanged",
            "second-unchanged",
            "third-unchanged",
            "independent-clean",
            "signed-first-unchanged",
            "signed-second-unchanged",
        ):
            inv = tag + "/inventory.json.gz"
            if inv not in all_names:
                continue
            cargo = row(inv)
            assert len(cargo["executables"]) == 102 and cargo["state"] == (
                adm["edit"][0] if tag == "old" else adm["edit"][1]
            )
            proc = row(tag + "/hardware.json")
            assert (
                proc["running"] == proc["enabled"] > 0
                and proc["instructions"] > 0
                and proc["status"] == 0
            )
            bucket = {}
            for path, v in cargo["executables"].items():
                matched = [k for k in specs if path.endswith(k)]
                if not matched:
                    continue
                (key,) = matched
                assert v["unit"] == specs[key]["owner"] and key not in bucket
                bucket[key] = v["elf"]["sha256"]
            assert len(bucket) == 50
            if tag in (
                "independent-clean",
                "signed-first-unchanged",
                "signed-second-unchanged",
            ):
                assert not any(
                    n.startswith(tag + "/") and n.endswith(".tsv.gz") for n in all_names
                )
                signed[tag] = bucket
                continue
            if tag + "-native.json.gz" not in all_names:
                continue
            originals = row(tag + "-native.json.gz")
            assert originals.keys() == specs.keys()
            hw = {}
            for key, m in originals.items():
                obs = raw(tag + "/" + m["log"])
                assert (
                    hashlib.sha256(obs).hexdigest() == m["raw_sha256"]
                    and bucket[key] == m["published_sha256"]
                )
                try:
                    p = certificate.projections(
                        obs.decode(), dict(specs[key], suffix=key)
                    )
                except (AssertionError, ValueError, IndexError, KeyError) as e:
                    assert (
                        not m["qualified"] and type(e).__name__ == m["refusal"]["type"]
                    )
                    hw[key] = {"qualified": False, "refusal": m["refusal"]}
                    continue
                assert m["qualified"] and all(m[k] == v for k, v in p.items()), key
                assert p["image_b3"] in (
                    physical["proc_image_b3"],
                    "dynamic-or-unknown",
                )
                assert p["emitted"]["path"] == m["output"] and p["emitted"]["bytes"] > 0
                hw[key] = dict(p, qualified=True, published_sha256=bucket[key])
            history[tag] = hw
        verdicts = {}
        for n in (x for x in z.namelist() if x.endswith("/test-list")):
            tag = n.split("/")[0]
            contents = raw(n)
            names = [v[:-6] for v in contents.splitlines() if v.endswith(b": test")]
            assert (
                len(set(names)) == len(names) == 200
                and names.count(b"commands::debug_command") == 1
            )
            out = raw(tag + "/stdout")
            failure = tag == "withheld-old-on-genuine-new"
            assert (
                b"test result: FAILED. 0 passed; 1 failed;"
                if failure
                else b"test result: ok. 1 passed; 0 failed;"
            ) in out
            if failure:
                assert b"script_tag" in out and b"source_text" in out
            verdicts[tag] = {
                "names_sha256": hashlib.sha256(contents).hexdigest(),
                "exit_expected": 101 if failure else 0,
                "stdout_sha256": hashlib.sha256(out).hexdigest(),
            }
        complete = "all-50-decisions.json" in all_names
        result = {
            "run": run,
            "head": head,
            "original_sha256": archive_sha,
            "admission": adm,
            "complete": complete,
            "verdicts": verdicts,
            "complete_histories": sorted(history),
            "signed_histories": sorted(signed),
        }
        if complete:
            assert (
                {
                    "old",
                    "edit",
                    "first-unchanged",
                    "second-unchanged",
                    "third-unchanged",
                }
                == set(history)
                and len(signed) == 3
                and len(verdicts) == 9
            )
            outer = row("all-50-decisions.json")
            enrolled = json.loads((HERE / "owner-costs.json").read_bytes())
            weights = {
                ("/" + "/".join(Path(k).parts[-4:])): v["native_instructions"]
                for k, v in enrolled["roles"].items()
            }
            assert (
                weights.keys() == specs.keys()
                and row("independent-signed.json.gz") == signed
            )
            result["decisions"] = {}
            for prev, curr in (
                ("old", "edit"),
                ("edit", "first-unchanged"),
                ("first-unchanged", "second-unchanged"),
                ("second-unchanged", "third-unchanged"),
            ):
                rea = {
                    k: certificate.classify(
                        history[prev][k],
                        history[curr][k],
                        signed["independent-clean"][k],
                    )
                    for k in specs
                }
                yes = sorted(k for k, v in rea.items() if not v)
                no = {k: r for k, r in rea.items() if r}
                assert yes == outer[curr]["qualified"] and no == outer[curr]["refused"]
                result["decisions"][curr] = {
                    "donor": prev,
                    "strict_equal_roles": yes,
                    "refused": no,
                    "historical_native_instructions_of_accepted": sum(
                        weights[k] for k in yes
                    ),
                    "historical_whole": enrolled["whole_observed"][0],
                    "necessary_zero_cost_half_is_reachable": 2
                    * sum(weights[k] for k in yes)
                    >= enrolled["whole_observed"][0],
                }
        return result


if __name__ == "__main__":
    print(
        json.dumps(
            open_result(Path(sys.argv[1]), *sys.argv[2:]), sort_keys=True, indent=2
        )
    )
