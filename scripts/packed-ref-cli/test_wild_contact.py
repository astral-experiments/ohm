"""Exercise the contact reader on untouched native ledgers from both real schedules."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import review


def main(kernel):
    packet = (
        kernel / "scripts/branch-return-execstop/group-v2/history/wild-schedules.zip"
    )
    assert (
        hashlib.sha256(packet.read_bytes()).hexdigest()
        == "6a1f3e23845c5afee41c8567a0cfc0171250bfca50056e2e5d6014e571100d10"
    )
    answers = {}
    with zipfile.ZipFile(packet) as z:
        for case, workers in (("one", [4]), ("both", [3, 4])):

            def read(name):
                return z.read(case + "/" + name)

            result = review.stock_schedule(read)
            assert result["schedule"] == dict(
                helper=2,
                workers=[3, 4],
                parked=workers,
                exited_before_group=[v for v in (3, 4) if v not in workers],
            )
            refused = {}
            variants = {
                "ELF": ("linked.elf", read("linked.elf") + b"\0"),
                "linked exit": ("run-linked.terminal.json", b'{"status":0}'),
                "link exit": ("wild.terminal.json", b'{"status":37}'),
                "diagnostic": ("wild.stderr", b"ld: error\n"),
                "command": (
                    "wild.command.json",
                    read("wild.command.json").replace(b"linked.elf", b"otherx.elf"),
                ),
                "missing worker": (
                    "wild.tsv",
                    b"\n".join(
                        r
                        for r in read("wild.tsv").splitlines()
                        if not r.startswith(b"T\t3\t")
                    )
                    + b"\n",
                ),
            }
            if case == "one":
                rows = read("wild.tsv").splitlines()
                early = next(r for r in rows if r.startswith(b"X\t3\t"))
                rows.remove(early)
                rows.insert(
                    next(i for i, r in enumerate(rows) if r.startswith(b"V\t")), early
                )
                variants["unparked worker late"] = (
                    "wild.tsv",
                    b"\n".join(rows) + b"\n",
                )
            for name, (key, value) in variants.items():
                try:
                    review.stock_schedule(lambda f: value if f == key else read(f))
                except ValueError as exc:
                    refused[name] = str(exc)
                else:
                    raise AssertionError(name)
            answers[case] = dict(result=result, corruptions_refused=refused)
    return answers


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1])), sort_keys=True))
