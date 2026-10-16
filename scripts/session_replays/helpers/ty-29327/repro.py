"""Run the original #29327 reproducers against this replay's saved binaries."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FIXTURES = Path(__file__).parent
TARGET = Path(os.environ["CARGO_TARGET_DIR"])
ROOT = TARGET / "ty-repro"
BINARIES = {"main": TARGET / "ty-baseline", "fixed": TARGET / "debug" / "ty"}

if sys.argv[1:] == ["baseline"]:
    ROOT.mkdir(exist_ok=False)
    for name in ("callable.py", "cached_classmethod.py"):
        shutil.copyfile(FIXTURES / name, ROOT / name)
    completed = subprocess.run(
        [str(BINARIES["fixed"]), "check", str(ROOT), "--output-format", "concise"],
        text=True,
        capture_output=True,
        timeout=30,
        cwd=ROOT,
    )
    output = completed.stdout + completed.stderr
    print(output, end="")
    diagnostics = re.findall(r"(?:error|warning)\[([^]]+)\]", output)
    if completed.returncode != 1 or diagnostics != ["invalid-method-override"] * 2:
        raise AssertionError((completed.returncode, diagnostics, output))
    for expected in ("cached_classmethod.py:14:9:", "callable.py:9:9:"):
        if expected not in output:
            raise AssertionError((expected, output))
    shutil.copy2(BINARIES["fixed"], BINARIES["main"])
    print("Verified both original diagnostics and saved the baseline binary.")
    raise SystemExit(0)
if sys.argv[1:] != ["verify"]:
    raise SystemExit("expected baseline or verify")

ATTRIBUTE = "invalid-attribute-override"
METHOD = "invalid-method-override"
UNUSED = "unused-ignore-comment"
MODES = {
    "unsuppressed": ("", [], [ATTRIBUTE], [ATTRIBUTE]),
    "attribute_ignore": (f"  # ty: ignore[{ATTRIBUTE}]", [], [METHOD], []),
    "method_ignore": (
        f"  # ty: ignore[{METHOD}]",
        [],
        [ATTRIBUTE, UNUSED],
        [ATTRIBUTE, UNUSED],
    ),
    "both_ignores": (
        f"  # ty: ignore[{ATTRIBUTE}, {METHOD}]",
        [],
        [],
        [UNUSED],
    ),
    "attribute_disabled": ("", ["--ignore", ATTRIBUTE], [METHOD], []),
    "all_attribute_rules_disabled": (
        "",
        [
            "--ignore",
            ATTRIBUTE,
            "--ignore",
            "invalid-property-type-override",
            "--ignore",
            "invalid-mutable-override",
        ],
        [METHOD],
        [],
    ),
}

results = []
for example in ["callable", "cached_classmethod"]:
    source = (ROOT / f"{example}.py").read_text()
    for mode, (comment, flags, before, after) in MODES.items():
        path = ROOT / f"{example}_{mode}.py"
        path.write_text(source.replace(f"  # ty: ignore[{ATTRIBUTE}]", comment))
        for version, binary in BINARIES.items():
            completed = subprocess.run(
                [str(binary), "check", str(path), "--output-format", "concise", *flags],
                text=True,
                capture_output=True,
                timeout=15,
                cwd=ROOT,
            )
            output = completed.stdout + completed.stderr
            actual = sorted(re.findall(r"(?:error|warning)\[([^]]+)\]", output))
            expected = sorted(before if version == "main" else after)
            if actual != expected or completed.returncode not in (0, 1):
                raise AssertionError((example, mode, version, expected, actual, output))
            results.append(
                {
                    "example": example,
                    "mode": mode,
                    "version": version,
                    "diagnostics": actual,
                }
            )

(ROOT / "verification.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"Verified {len(results)} baseline and fixed diagnostic results.")
