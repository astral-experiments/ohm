"""Reopen the actual interleaved logs; only independent unit/doc command outputs can authorize a pass."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

D = Path(__file__).resolve().parent
sys.path.insert(0, str(D))
from qualify_e import unit_record, doc_record, individual, DOC_TEST


def refuses(call):
    try:
        call()
    except (ValueError, KeyError):
        return 1
    raise ValueError("mixed or damaged suite accepted")


def qualify():
    rows = json.loads((D / "inputs/suite-controls.json").read_bytes())
    history = {}
    for role, row in rows.items():
        raw = gzip.decompress((D / "inputs" / row["local"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == row["raw_sha256"]
        history[role] = raw.decode()
    expected = re.findall(r"(?m)^test (\S+) \.\.\. ok$", history["K"])
    assert len(expected) == len(set(expected)) == 10 and sorted(expected) == rows["K"]["named_units"]
    refused = 0
    for role, crate, names in (("E", "rustc_fs_util", []), ("K", "rustc_incremental", expected)):
        # A combined stdout is insufficient even when both zero-test footers are green.
        prior = history[role]
        refused += refuses(lambda: unit_record(prior, crate, names))
        refused += refuses(lambda: doc_record(prior, crate))
    original = history["E"]
    assert (
        re.findall(r"(?m)^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored", original)
        == [("0", "0", "0")] * 2
    )
    assert original.index("   Doc-tests rustc_fs_util") < original.index("running 0 tests")
    for crate, names in (("rustc_fs_util", []), ("rustc_incremental", expected)):
        # Mechanical projection from the physically original text: the new official run
        # must produce each stream itself, with its own checked successful status and argv.
        lines = (history["E"] if not names else history["K"]).splitlines()
        ux = next(s for s in lines if "Running unittests" in s and ("/out/" + crate + "-") in s)
        doc = next(s for s in lines if s.strip() == "Doc-tests " + crate)

        def footer(t):
            return next(
                s
                for s in lines
                if s.startswith(f"test result: ok. {t[0]} passed; 0 failed; {t[1]} ignored;")
            )

        uf = footer((len(names), 0))
        df = footer((0, int(bool(names))))
        u = (
            "\n".join(
                [ux, f"running {len(names)} tests", *["test " + s + " ... ok" for s in names], uf]
            )
            + "\n"
        )
        doc_items = [s for s in lines if s == "test " + DOC_TEST + " ... ignored"] if names else []
        dx = "\n".join([doc, f"running {len(doc_items)} tests", *doc_items, df]) + "\n"
        assert unit_record(u, crate, names) == sorted(names) and doc_record(dx, crate) == (
            [DOC_TEST] if names else []
        )
        for text, parse, ft in (
            (u, lambda s: unit_record(s, crate, names), uf),
            (dx, lambda s: doc_record(s, crate), df),
        ):
            refused += refuses(lambda: parse(text.replace(ft, "")))
            refused += refuses(lambda: parse(text.replace("0 failed", "1 failed")))
            refused += refuses(lambda: parse(text + ft + "\n"))
        for w, t in (("--tests", u), ("--doc", dx)):
            raw = t.encode()
            cmd = {
                "returncode": 0,
                "argv": ["./x", "test", w, "compiler/" + crate],
                "cwd": "/tmp/ohm-gnu-renderer-source-native/rust",
                "output_sha256": hashlib.sha256(raw).hexdigest(),
            }
            assert individual(cmd, raw, crate, w) == t
            refused += refuses(lambda: individual(cmd | {"returncode": 1}, raw, crate, w))
            refused += refuses(
                lambda: individual(
                    cmd | {"argv": ["./x", "test", "compiler/" + crate]}, raw, crate, w
                )
            )
            refused += refuses(lambda: individual(cmd, raw + b"!", crate, w))
    print(
        json.dumps(
            {
                "originals": rows,
                "E_mixed_no_attribution": True,
                "K_physical_named_units": len(expected),
                "genuine_new_independently_invoked_suites": False,
                "mechanical_rejection_cases": refused,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    qualify()
