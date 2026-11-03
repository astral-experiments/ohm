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
    return {
        "original_bytes": path.stat().st_size,
        "zip_sha256": sha,
        "native_owners_outside_50_on_edit": value["extra_edited_native"]["P-exec-edit"],
        "native_cold_sha256": p["published"],
        "cold_candidate_receipt_bytes": c["metadata_bytes"],
        "source_arm_cold_fresh": 0,
        "clock_rows": value["clocks"],
        "candidate_first_unchanged": None,
        "terminal": "C-edit staged native ready marker observed before rename",
        "negative_argvs": ["duplicate -o", "different output", "different inode"],
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), indent=2, sort_keys=True))
