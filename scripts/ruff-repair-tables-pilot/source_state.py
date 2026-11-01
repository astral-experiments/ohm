"""Set and attest original A/B, the literal E0308 source, and Ruff's one-line UP035 change."""

import hashlib
import subprocess as sp
from pathlib import Path
from protocol import need

PARSER = "crates/ruff_python_parser/src/lib.rs"
RULE = "crates/ruff_linter/src/rules/pyupgrade/rules/deprecated_import.rs"
BAD = b"\nconst ohm_branch_switch_invalid: () = 1u32;\n"
TOKEN = b'    "no_type_check",\n'
REPLACEMENT = TOKEN + b'    "no_type_check_decorator",\n'
PATCH = Path(__file__).resolve().parent / "inputs/up035.patch"
LOCK = "839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"


def select(tree, names, revs, trees, branch, kind):
    def git(*args, input=None):
        return sp.check_output(["git", "--no-optional-locks", "-C", tree, *args], input=input)

    def lines(*args):
        return git(*args).decode().splitlines()

    need(
        not lines("diff", "--cached", "--name-only")
        and not lines("ls-files", "--others", "--exclude-standard"),
        "unregistered Ruff input",
    )
    changed = lines("diff", "--name-only")
    need(changed in ([], [RULE], [PARSER]), "unknown Ruff working source")
    want = revs[branch]
    cur = git("rev-parse", "HEAD").decode().strip()
    for p, k in ((RULE, "private"), (PARSER, "invalid")):
        if changed == [p]:
            content = git("show", "HEAD:" + p)
            mod = content + BAD if k == "invalid" else content.replace(TOKEN, REPLACEMENT)
            need((tree / p).read_bytes() == mod, "not the enrolled working-tree edit")
            if cur != want or k != kind:
                (tree / p).write_bytes(content)
                changed = []
    if cur != want:
        need(not changed, "dirty prior Ruff checkout")
        git("switch", "-q", names[branch])
    if not changed and kind == "private":
        need(
            hashlib.sha256(PATCH.read_bytes()).hexdigest()
            == "3736a3d7d473e0abc20281196885f520bc64bb36a56110daf3f16f0be0babc0d",
            "foreign UP035 hunk",
        )
        git("apply", "--reverse", "--check", str(PATCH))
        git("apply", "--reverse", str(PATCH))
    elif not changed and kind == "invalid":
        clean = git("show", "HEAD:" + PARSER)
        need(
            clean.count(b"\n") + 2 == 626 and (tree / PARSER).read_bytes() == clean,
            "wrong diagnostic source line",
        )
        (tree / PARSER).write_bytes(clean + BAD)
    delta = {"clean": [], "private": [RULE], "invalid": [PARSER]}[kind]
    need(
        lines("diff", "--name-only") == delta
        and git("rev-parse", "HEAD").decode().strip() == want
        and git("rev-parse", "HEAD^{tree}").decode().strip() == trees[branch]
        and git("symbolic-ref", "--short", "HEAD").decode().strip() == names[branch]
        and hashlib.sha256((tree / "Cargo.lock").read_bytes()).hexdigest() == LOCK,
        "different whole historical checkout/input",
    )
    return {
        "commit": want,
        "tree": trees[branch],
        "branch": names[branch],
        "lock": LOCK,
        "modified": delta,
        "inputs": {n: hashlib.sha256((tree / n).read_bytes()).hexdigest() for n in (RULE, PARSER)},
    }
