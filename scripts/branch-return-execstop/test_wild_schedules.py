"""Replay two genuine stock Wild thread schedules and recomputed corrupt variants."""

import copy
import hashlib
import json
import sys
import types
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import group_checks as checks

PACKET = "6a1f3e23845c5afee41c8567a0cfc0171250bfca50056e2e5d6014e571100d10"
PREVIOUS = "e7ab5664b75ea6029eceae7392801152afb528690c95c3b5a06cbd609faa19de"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def refuse(call, *args, reason=None):
    try:
        call(*args)
    except ValueError as e:
        if reason:
            assert reason in str(e), (reason, e)
        return str(e)
    raise AssertionError("accepted a missing or corrupted native observation")


def body(rows):
    return ("\n".join("\t".join(r) for r in rows) + "\n").encode("ascii")


def linked(elf, command, status, stdout, stderr, expected):
    checks.need(
        sha(elf) == checks.OUTPUT
        and command["argv"] == [expected]
        and status == {"status": 37}
        and not stdout
        and not stderr,
        "different complete linked ELF or verdict",
    )


def verify():
    path = HERE / "group-v2/history/wild-schedules.zip"
    assert sha(path.read_bytes()) == PACKET
    result = {}
    with zipfile.ZipFile(path) as z:
        history = json.loads(z.read("history.json"))
        assert set(z.namelist()) == set(history["sha256"]) | {"history.json"}
        assert all(sha(z.read(k)) == h for k, h in history["sha256"].items())
        assert history["one"] == dict(
            run=41326096604,
            job=124906234610,
            artifact=13091376595,
            archive_sha256="2fed51e42db71065bfeda1446c772ab0e07f34aba3cbd1d69102cadbfcefd343",
            bytes=564929,
            members=137,
            scores=0,
        )
        old = z.read("legacy-group-checks.py")
        assert sha(old) == PREVIOUS
        legacy = types.ModuleType("pre_schedule_fixture")
        legacy.__file__ = str(HERE / "group_checks.py")
        exec(compile(old, legacy.__file__, "exec"), legacy.__dict__)
        for case, count in (("one", 1), ("both", 2)):

            def data(name):
                return z.read(case + "/" + name)

            raw, host = data("wild.tsv"), json.loads(data("host.json"))
            args = json.loads(data("wild.command.json"))["argv"]
            command = [
                host["wild"],
                host["tools"] + "/start.o",
                "-o",
                host["out"] + "/group-v2/linked.elf",
            ]
            assert args == [
                host["tools"] + "/observe",
                host["out"] + "/group-v2/wild.tsv",
                "--",
                *command,
            ]
            assert json.loads(data("wild.terminal.json")) == {"status": 0} and not data(
                "wild.stderr"
            )
            ident = host["identities"]
            link_args = [
                data("linked.elf"),
                json.loads(data("run-linked.command.json")),
                json.loads(data("run-linked.terminal.json")),
                data("run-linked.stdout"),
                data("run-linked.stderr"),
                command[-1],
            ]
            linked(*link_args)
            assert (
                data("source/group-v2/start.s")
                == (HERE / "group-v2/start.s").read_bytes()
            )
            joint = [data("wild.stdout"), "wild", command, ident]
            actual = checks.positive(raw, *joint)
            assert (
                actual["counts"]["Q"] == count
                and len(actual["worker_schedule"]["workers"]) == 2
            )
            assert len(actual["worker_schedule"]["exited_before_group"]) == 2 - count
            if count == 2:
                prior = json.loads(data("qualified.json"))
                assert (
                    sha(data("qualified.json"))
                    == history["both"]["fixture_qualified_sha256"]
                )
                assert legacy.positive(raw, *joint) == prior["native"]["wild"]
            else:
                refuse(legacy.positive, raw, *joint, reason="two parked threads")
            result[case] = dict(
                raw=sha(raw), schedule=actual["worker_schedule"], refused={}
            )
            denied = result[case]["refused"]
            original = checks.records(raw)

            def alter(name, mutation, *, expected=None):
                rows = copy.deepcopy(original)
                mutation(rows)
                failed = body(rows)
                if expected:
                    # Prove that generic complete lifetimes alone would accept this edit.
                    checks.reader.parse(failed, expected_code=0, expected_schema=3)
                denied[name] = refuse(checks.positive, failed, *joint, reason=expected)

            def row(rows, tag, life=None):
                return next(
                    r
                    for r in rows
                    if r[0] == tag and (life is None or r[1] == str(life))
                )

            for life in actual["worker_schedule"]["workers"]:
                for tag in ("B", "X", "T"):
                    alter(
                        f"omit-{life}-{tag}",
                        lambda rs, t=tag, w=life: rs.remove(row(rs, t, w)),
                    )
            for tag in ("E", "P", "N", "C", "G", "Q", "V"):
                alter("omit-" + tag, lambda rs, t=tag: rs.remove(row(rs, t)))
            alter("wrong-park-owner", lambda rs: row(rs, "Q").__setitem__(3, "1"))
            alter("wrong-worker-pid", lambda rs: row(rs, "Q").__setitem__(2, "1"))

            def nonzero(rs):
                for tag in ("X", "T"):
                    row(rs, tag, actual["worker_schedule"]["workers"][0])[-1] = "256"

            alter("rebound-nonzero", nonzero)

            def forgery(rs):
                row(rs, "I")[-1] = "f" * 64

            fake_rows = copy.deepcopy(original)
            forgery(fake_rows)
            fake_ident = copy.deepcopy(ident)
            fake_ident["wild"]["sha256"] = "f" * 64
            denied["physically-rebound-wrong-linker"] = refuse(
                checks.positive, body(fake_rows), *joint[:-1], fake_ident
            )
            denied["wrong-output-argv"] = refuse(
                checks.positive,
                raw,
                joint[0],
                "wild",
                [*command[:-1], command[-1] + ".bad"],
                ident,
            )
            for index, value, label in (
                (0, link_args[0][:-1], "truncated-image"),
                (2, {"status": 0}, "wrong-native-exit"),
                (3, b"x", "changed-stdout"),
                (4, b"x", "changed-stderr"),
            ):
                changed = list(link_args)
                changed[index] = value
                denied[label] = refuse(linked, *changed)
            changed = bytearray(link_args[0])
            text = bytes.fromhex("48c7c03c000000bf250000000f05")
            assert changed.count(text) == 1
            changed[changed.index(text) + 8] = 38
            denied["changed-exit-in-text"] = refuse(
                linked, bytes(changed), *link_args[1:]
            )

            def zero(rs):
                rs[:] = [r for r in rs if r[0] not in ("G", "Q", "V")]
                rs[-1][7:9] = ["0", "0"]

            alter("no-park", zero, expected="must fork once and park")
            if count == 1:

                def late(rs):
                    early = actual["worker_schedule"]["exited_before_group"][0]
                    x = row(rs, "X", early)
                    rs.remove(x)
                    rs.insert(rs.index(row(rs, "V")), x)

                alter("unparked-live-past-group", late, expected="did not exit before")
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
