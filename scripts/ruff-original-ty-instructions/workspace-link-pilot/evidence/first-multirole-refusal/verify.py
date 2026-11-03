"""Reopen all recorded stages and challenge the extra real shared-library owner's argv."""

from pathlib import Path
import gzip, hashlib, json, sys
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
import read_pilot as r


def main(path):
    sha = "d3e60812994bc68b823804060515b78fb041eb95f4ca9308fb70b9754b950ecc"
    value = r.intake(
        path, sha, "a7664d69a0e77680453c5b72f783a741d2b81e31", 41732263858, 23
    )
    assert (
        not value["complete"] and not value["qualified"] and value["stage_count"] == 9
    )
    assert (
        len(value["extra_edited_native"]["P-exec-edit"]) == 7
        and not value["extra_edited_native"]["P-exec-warm"]
    )
    assert set(value["clocks"]) == {
        "P-old",
        "P-edit",
        "P-warm1",
        "P-warm2",
        "P-warm3",
        "P-reverse-old",
        "C-old",
    }
    with ZipFile(path) as z:

        def row(n):
            return json.loads(gzip.decompress(z.read(n)))

        p, c = (row(a + "-old-receipt.json.gz") for a in ("P", "C"))
        assert len(p["published"]) == 50 and p["published"] == c["published"]
        assert (
            c["actions"] == {"full": 48}
            and c["proof_refusals"] == {}
            and c["native_bytes_consumed"] == 12224797242
            and c["signed_output_reads_for_donor"] == 3581308080
            and c["metadata_bytes"] == 13496
        )
        code = z.read("C-edit/stderr")
        assert (
            b'assert pid.isdecimal() and notice.read_bytes()==b"complete\\n"' in code
            and b"AssertionError" in code
        )
        scope = "P-exec-edit/"
        (owner,) = [
            x
            for x in row(scope + "owner-census.json.gz")["roles"]
            if x["mode"] == "Wild"
            and x["trigger"] == "exec"
            and x["output"].endswith("/libty_wasm.so")
        ]
        src = z.read(scope + "tasks/" + owner["argv"])
        fields = r.wild_argv(src, owner)
        args = fields[4:-1]
        assert args.index(b"-o") + 1 == 15 and args[19].startswith(b"-L")
        for label, bad in [
            ("added output option", fields[:-1] + [b"-o", b"other", b""]),
            ("other output", fields[:19] + [b"/unrelated-new.so"] + fields[20:]),
            ("other physical inode", fields[:2] + [b"999"] + fields[3:]),
        ]:
            new = b"\0".join(bad)
            entry = {**owner, "argv_sha256": hashlib.sha256(new).hexdigest()}
            try:
                r.wild_argv(new, entry)
            except AssertionError:
                pass
            else:
                raise AssertionError("Accepted " + label)
        scope = "C-edit/"
        assert json.loads(z.read(scope + "stdout.jsonl").splitlines()[-1]) == {
            "reason": "build-finished",
            "success": True,
        }
        failed_meter = json.loads(z.read(scope + "hardware.json"))
        assert (
            failed_meter["status"] == 256
            and failed_meter["running"] == failed_meter["enabled"]
        )
        image = json.loads(z.read("physical.json"))["image_b3"]
        full = r.release_scope.for_release(23)
        spec = {
            k: full[k]
            for k in json.loads((HERE.parent.parent / "accepted-48.json").read_bytes())
        }
        paired = {}
        fallback = {}
        for phase in ("C-old", "C-edit"):
            raw_by_role = {}
            for name in z.namelist():
                if not r.re.fullmatch(phase + r"/actor-[0-9]+\.tsv\.gz", name):
                    continue
                raw = gzip.decompress(z.read(name)).decode()
                before = r.coordinator.before(raw, spec, image)
                rows = r.coordinator.rows(raw)
                assert (
                    rows["VERIFIED"] == [[]]
                    and len(rows["EMITTED"]) == 1
                    and not rows["FRESH-PUBLISH"]
                )
                role = before["role"]
                assert role not in raw_by_role
                raw_by_role[role] = (before, rows["EMITTED"][0][2:4])
                if phase == "C-edit":
                    assert len(rows["MISS"]) == 1
                    reason = rows["MISS"][0][0]
                    fallback[reason] = fallback.get(reason, 0) + 1
            assert raw_by_role.keys() == spec.keys()
            paired[phase] = raw_by_role
        assert fallback == {"coordinator-timeout": 34, "coordinator-full": 14}
        old, new = paired.values()
        assert all(old[k][0]["key"] != new[k][0]["key"] for k in spec)
        changed_native_input = [
            k
            for k in sorted(spec)
            if old[k][0]["parts"]["native_inputs"]
            != new[k][0]["parts"]["native_inputs"]
        ]
        changed_output = {
            k: [old[k][1], new[k][1]] for k in sorted(spec) if old[k][1] != new[k][1]
        }
        assert len(changed_native_input) == 16 and len(changed_output) == 7
    return {
        "original_bytes": path.stat().st_size,
        "zip_sha256": sha,
        "native_owners_outside_50_on_edit": value["extra_edited_native"]["P-exec-edit"],
        "native_cold_sha256": p["published"],
        "cold_candidate_receipt_bytes": c["metadata_bytes"],
        "source_arm_cold_fresh": 0,
        "clock_rows": value["clocks"],
        "candidate_first_unchanged": None,
        "genuine_cargo_completed_edited_source": True,
        "failed_supervisor_meter": failed_meter,
        "edited_all_48_full_emissions": fallback,
        "changed_native_input_rows": changed_native_input,
        "changed_edited_output_bytes_and_blake3": changed_output,
        "terminal": "C-edit staged native ready marker observed before rename",
        "negative_argvs": ["duplicate -o", "different output", "different inode"],
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), indent=2, sort_keys=True))
