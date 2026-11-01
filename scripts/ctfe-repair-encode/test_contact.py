"""Tiny adversarial checks plus optional readback of the four real native fixtures."""

import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contact
import contact_kernel as kernel
import evidence as ev

CMD = [
    "cargo",
    "+ohm",
    "build",
    "--locked",
    "--offline",
    "-j2",
    "-p",
    "repair_app",
    "--message-format=json",
]
UNITS = [["repair_dep", "lib"], ["repair_app", "bin"]]


class Contact(unittest.TestCase):
    def test_map(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            file = Path("/canonical/sdk") / ev.DRIVER
            # The reference FD stat dev=33, kernel VMA device=32. Require a second,
            # independently witnessed executable mmap of the real tracee's fd.
            ref = "33\t7614611\t100000\t2000\n2000-3000 r--p 00000000 00:20 7614611 " + str(file) + "\n"
            fd = "33\t7614611\t100000\t3\t9000\t1000\t3000\t" + str(file) + "\n"
            row = "9000-a000 r-xp 00003000 00:20 7614611 " + str(file)

            def check(reference=ref, actual=fd, rows=None):
                (d / "driver.reference").write_text(reference)
                (d / "r.mmap").write_text(actual)
                return ev.mapped_driver(
                    d, "r", file, (33, 7614611, 100000), [row] if rows is None else rows
                )

            self.assertEqual(check(), [row])
            for args in [
                dict(reference=ref.replace("r--p", "r-xp")),
                dict(reference=ref.replace("00:20", "00:21")),
                dict(actual=fd.replace("7614611", "7614612")),
                dict(actual=fd.replace("33\t", "32\t")),
                dict(actual=fd.replace("canonical", "renamed")),
                dict(actual=fd.replace("9000", "8000")),
                dict(rows=[row.replace("00003000", "00002000")]),
                dict(rows=[row, row]),
                dict(rows=[row.replace("canonical", "elsewhere")]),
                dict(rows=[row.replace("r-xp", "r--p")]),
                dict(rows=[row.replace("7614611", "76146")]),
            ]:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    check(**args)

    def test_native(self):
        sdk = Path("/sdk")
        proxy = Path("/proxies")
        rust = str(sdk / "bin/rustc")
        cargo = str(sdk / "bin/cargo")
        wild = str(sdk / ev.WILD)
        raw = []

        def add(pid, name, a):
            raw.append(f"{pid} execve({json.dumps(name)}, {json.dumps(a)}, 0x20 /* 4 vars */) = 0")

        add(10, str(proxy / "cargo"), CMD)
        add(10, cargo, [cargo, *CMD[2:]])
        add(25, rust, [rust, "--crate-name", "repair_dep", "--crate-type", "lib"])
        add(27, rust, [rust, "--crate-name", "repair_app", "--crate-type", "bin"])
        for pid, program in enumerate(contact.AUX, 33):
            add(pid, program, [program, "-o", "/target/repair_app"])
        add(39, wild, [wild, "-o", "/target/repair_app"])

        def inspect(rows, images=None):
            return contact.topology("\n".join(rows), sdk, proxy, CMD, UNITS, captured=images)

        good = inspect(raw)
        self.assertEqual(len(good["compilers"]), 2)
        rows = contact.execs("\n".join(raw))[1:]
        captures = {
            str(pid): {"role": ("cargo" if exe == cargo else "rustc" if exe == rust else "wild"), "argv": a}
            for pid, exe, a in rows
            if exe not in contact.AUX
        }
        self.assertEqual(inspect(raw, captures), good)
        for x in [
            raw[:-1],
            raw + [raw[2]],
            raw[:2] + [raw[2].replace('execve("/sdk/bin/rustc"', 'execve("/foreign"')] + raw[3:],
            raw + [raw[-1].replace("39 exec", "40 exec")],
            raw + [raw[3].replace(" = 0", " <unfinished ...>")],
            raw + ["69 ???( <unfinished ...>"],
            raw[:-1] + [raw[-1].replace("execve(", "execveat(")],
        ]:
            with self.assertRaises(ValueError):
                inspect(x)
        with self.assertRaises(ValueError):
            inspect(raw, dict(captures, extra=captures["39"]))
        with self.assertRaises(ValueError):
            inspect(raw[:-1] + [raw[-1].replace("/target/repair_app", "/foreign/repair_app")], captures)

    def test_flags_and_placements(self):
        work = Path("/qa/work")
        q = dict(
            reason="compiler-artifact",
            package_id="registry+x#a",
            target={"name": "m"},
            features=[],
            profile={},
            filenames=[str(work / "build/a.rlib")],
            executable=None,
        )
        a = contact.placement([q], work, full=False)
        item = copy.deepcopy(q)
        item["filenames"] = [str(work / "target/a.rlib")]
        self.assertNotEqual(a, contact.placement([item], work, full=False))
        with self.assertRaises(ValueError):
            contact.placement([item, item], work, full=False)
        with self.assertRaises(ValueError):
            contact.placement([dict(q, filenames=["/foreign/a.rlib"])], work, full=False)
        self.assertNotIn("table-notify", " ".join(contact.launch("O", Path("/a/b/r"), Path("/sdk"), CMD)))
        for m in ("P", "B"):
            self.assertIn("/a/tools/table-notify", contact.launch(m, Path("/a/b/r"), Path("/sdk"), CMD))


def verified(data, legacy=None, observer_source=None):
    reader = kernel.decoder(kernel.package(observer_source)) if observer_source is not None else None
    result = {}
    cmds = {}
    native_elf = []
    for tag, mode in (
        ("ordinary/pass", "O"),
        ("notify/pass", "P"),
        ("notify/blocked", "B"),
        ("preload/pass", "L"),
    ):
        q = legacy if mode == "L" and legacy is not None else data / tag
        gate = q / "control"
        # Sources, intact SDK contents, independent Y/X transitions, E0308 and linked empty.
        source = json.loads((q / "source.json").read_bytes())
        files = json.loads((q / "sdk-files.json").read_bytes())
        ev.need(
            len(files) == 81
            and source == {k: [v[0], v[3], v[4]] for k, v in files.items()}
            and contact.digest({k: [v[0], v[4], v[3]] for k, v in files.items()})
            == "a51417a5cb8bdc6d20570b879e52e19fd07c40e686410815544a113779b6ed57"
            and ev.sha(q / "repair.elf")
            == json.loads((q / "repair.native.json").read_bytes())["elf"]
            == json.loads((q / "empty.native.json").read_bytes())["elf"]
            and all(x[0] == 0 for x in json.loads((q / "host-ownership.json").read_bytes()).values()),
            "different SDK/native/reference/ownership",
        )
        for phase, value in (
            ("Y-B", 17),
            ("X-A", 29),
            ("X-B", 17),
            ("repair", 37),
            ("settled", 37),
            ("empty", 37),
        ):
            got = json.loads((q / (phase + ".native.json")).read_bytes())
            ev.need(got["status"] == 0 and got["stdout"] == str(value) + "\n", "wrong executed artifact")
        bad = list(map(json.loads, gzip.open(q / "invalid.stdout.gz")))
        ev.need(
            any((x.get("message", {}).get("code") or {}).get("code") == "E0308" for x in bad),
            "absent real error",
        )
        raw = {}
        for phase in ("Y-B", "repair", "settled", "empty"):
            rows = list(map(json.loads, gzip.open(q / (phase + ".stdout.gz"))))
            (itoa,) = [e for e in rows if e.get("target", {}).get("name") == "itoa"]
            raw[phase] = [itoa["fresh"], itoa["filenames"]]
            ev.need(itoa["package_id"].endswith("#itoa@1.0.15"), "wrong registry control")
        orig = raw["Y-B"][1]
        ev.need(
            all("/build/debug/build/registries/v2-" in n for n in orig)
            and raw["settled"] == [True, orig]
            and raw["empty"] == [False, orig],
            "not a trusted registry history",
        )
        if mode == "L":
            ev.need(
                raw["repair"][0] is False
                and all("/target/debug/build/workspaces/" in n for n in raw["repair"][1]),
                "legacy loader did not perturb the authentic graph",
            )
            result[mode] = {"legacy_registry_moved": True}
            continue
        ev.need(raw["repair"] == [True, orig], "registry moved or was recompiled")
        if mode == "O":
            trace = q / "ordinary.exec"
            imgs = None
            root = Path(orig[0].partition("/work/")[0])
            sdk = root / "runner/_temp/ohm-branch-object-qa/home/.rustup/toolchains/ohm"
        else:
            trace = q / "actual.exec"
            sdk = Path(next(gate.glob("rustc-*.image")).read_text().strip().split("\t")[-1]).parents[1]
            selected = (gate / "config").read_text().splitlines()[1:]
            owners = (gate / "owners").read_text().splitlines()
            imgs, events = contact.listener(gate, mode, sdk, selected, owners, files)
            before = json.loads((q / "before.json").read_bytes())
            after = json.loads((q / "after.json").read_bytes())
            chosen = Path(selected[0]).name
            placement = ev.routes(
                before,
                after,
                imgs,
                events,
                [chosen],
                mode == "B",
                extra_passthrough=[Path(o).name for o in owners if o not in selected],
            )
            ev.need(placement[chosen]["packed_pair"] == (mode == "P"), "wrong real table intervention")
        actual_command = json.loads((q / "repair.command.json").read_bytes())["argv"]
        expected_notifier = actual_command[actual_command.index("--") + 1 :] if imgs is not None else None
        if reader is None:
            top = contact.topology(
                trace.read_text(),
                sdk,
                sdk.parents[2] / ".cargo/bin",
                CMD,
                UNITS,
                captured=imgs,
                notifier=expected_notifier,
            )
        else:
            trace = q / "positive.tsv"
            catalog = json.loads((q / "exec-before.json").read_bytes())
            ev.need(catalog == json.loads((q / "exec-after.json").read_bytes()), "replaced native tool")
            project = Path(orig[0].partition("/work/")[0]) / "project"

            def checked(raw, cat, commands=UNITS, captures=imgs):
                return kernel.topology(
                    reader,
                    raw,
                    cat,
                    files,
                    sdk,
                    sdk.parents[2] / ".cargo/bin",
                    CMD,
                    commands,
                    project,
                    captured=captures,
                    notifier=expected_notifier,
                )

            raw_events = trace.read_bytes()
            top = checked(raw_events, catalog)

            def reject(fn):
                try:
                    fn()
                except ValueError:
                    return
                raise ValueError("malformed physical kernel control passed")

            reject(lambda: checked(raw_events.rsplit(b"\n", 2)[0] + b"\n", catalog))
            reject(lambda: checked(raw_events, catalog, UNITS[:-1]))
            reject(lambda: checked(raw_events.replace(b"OK\t", b"REFUSE\t", 1), catalog))
            for who, column, replacement in (
                (sdk / "bin/rustc", 0, "e" * 64),
                (sdk / ev.WILD, 2, 155),
                (Path(contact.AUX[0]), 4, 35),
            ):
                corrupt = copy.deepcopy(catalog)
                corrupt[str(who)][1][column] = replacement
                reject(lambda: checked(raw_events, corrupt))
            # Swap the installed pathname only in an otherwise complete positive exec record.
            fields = [line.split(b"\t") for line in raw_events.splitlines()]
            for row in fields:
                if row[0] == b"E" and bytes.fromhex(row[6].decode()) == str(sdk / "bin/rustc").encode():
                    row[6] = b"/foreign/bin/rustc".hex().encode()
                    break
            else:
                raise ValueError("real compiler absent")
            reject(lambda: checked(b"".join(b"\t".join(row) + b"\n" for row in fields), catalog))
        cmds[mode] = top["compilers"]
        native_elf.append(ev.sha(q / "repair.elf"))
        result[mode] = {
            "native": native_elf[-1],
            "trusted_registry_unchanged": True,
            "rustc": len(cmds[mode]),
            "wild": 1,
            "raw_exec": ev.sha(trace),
            "kernel": top.get("kernel"),
            "notifier_status": None if imgs is None else (gate / "notify.status").read_text().strip(),
        }
    ev.need(
        len(set(native_elf)) == 1 and cmds["O"] == cmds["P"] == cmds["B"],
        "different compiler arguments or linked native payload",
    )
    return result


if __name__ == "__main__":
    if sys.argv[1:2] == ["--v3-native"]:
        print(json.dumps(verified(*map(Path, sys.argv[2:])), sort_keys=True, indent=2))
    elif sys.argv[1:2] == ["--native"]:
        print(
            json.dumps(
                verified(Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) == 4 else None),
                sort_keys=True,
                indent=2,
            )
        )
    else:
        unittest.main()
