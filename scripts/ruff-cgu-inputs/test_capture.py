"""Exercise the genuine Linux exec boundary used by the structural diagnostic."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HELPER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    for (int i = 0; i < argc; ++i) fwrite(argv[i], strlen(argv[i]) + 1, 1, stdout);
    const char *marker = getenv("OHM_CGU_REQUEST");
    fprintf(stderr, "%s\n%s\n%s\n", marker ? marker : "absent", getenv("BEFORE"), getenv("AFTER"));
    return 0;
}
"""


def exercise(binary):
    with tempfile.TemporaryDirectory(prefix="ohm-cgu-exec-") as temp:
        work = Path(temp)
        helper = work / "ordinary-elf"
        (work / "helper.c").write_text(HELPER)
        subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(work / "helper.c"), "-o", helper],
            check=True,
        )
        other = work / "independent-elf"
        other.write_bytes(helper.read_bytes())
        other.chmod(0o700)
        flag = "-Csave-temps=yes"
        for label, mode, owner, exe, selected in (
            ("ordinary", "observe", "ruff_linter", helper, True),
            ("scope", "capture", "ruff_linter", helper, True),
            ("second", "capture", "ruff_workspace", helper, True),
            ("other-crate", "capture", "ruff_python_ast", helper, False),
            ("other-inode", "capture", "ruff_linter", other, False),
        ):
            stage = work / label
            stage.mkdir()
            env = {
                "PATH": os.environ["PATH"],
                "BEFORE": "retained-before",
                "OHM_CGU_REQUEST": flag,
                "AFTER": "retained-after",
            }
            args = [
                str(exe),
                "--crate-name",
                owner,
                "--crate-type",
                "lib",
                "--emit=dep-info,metadata,link",
                "--out-dir",
                str(work),
            ]
            result = subprocess.run(
                [binary, stage, helper, mode, *args], env=env, capture_output=True, check=False
            )
            assert result.returncode == 0, (label, result.returncode, result.stderr)
            changed = selected and mode == "capture"
            expected = args + ([flag] if changed else [])
            assert result.stdout == b"".join(os.fsencode(s) + b"\0" for s in expected)
            assert result.stderr.decode().splitlines() == [
                "absent" if changed else flag,
                "retained-before",
                "retained-after",
            ]
            rows = [json.loads(x) for x in (stage / "rustc.jsonl").read_bytes().splitlines()]
            assert len(rows) == int(exe == helper) and (stage / owner).exists() == selected
            if selected:
                assert (stage / owner / "observed.nul").read_bytes() == result.stdout
                assert (stage / owner / "original.nul").read_bytes() == b"".join(
                    os.fsencode(s) + b"\0" for s in args
                )
                process = json.loads((stage / owner / "process.json").read_bytes())
                assert (
                    process["pid"] == rows[0]["pid"]
                    and process["argc"] == [len(args), len(expected)]
                    and process["capture"] == changed
                )
                assert process["envc"] == [4, 4 - int(changed)] and process["aux_pairs"] > 1
        # For the wrong environment the child must never get to its main function.
        bad = work / "missing"
        bad.mkdir()
        p = subprocess.run(
            [binary, bad, helper, "capture", helper, "--version"],
            env={"PATH": os.environ["PATH"]},
            capture_output=True,
            check=False,
        )
        assert p.returncode == 125 and not p.stdout and not list(bad.iterdir())
    print("Both target owners, observation, distinct-inode, unselected crate, and missing request passed.")


if __name__ == "__main__":
    exercise(Path(sys.argv[1]).resolve(strict=True))
