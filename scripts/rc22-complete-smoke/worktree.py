"""Additional real Git worktree using the package installed by the complete smoke."""

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, need, save, sha


def main():
    root, smoke, receipt = map(Path, sys.argv[1:])
    donor = smoke / "registry-crate"
    child = smoke / "qa-real-worktree"
    env = dict(
        os.environ,
        CARGO_BUILD_BUILD_DIR=str(smoke / "shared-build"),
        CARGO_TARGET_DIR=str(smoke / "registry-target"),
        CARGO_NET_OFFLINE="true",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    cli = ["cargo", "+" + CFG["release"]]
    log = []

    def command(args, cwd=donor, custom=None, want=0):
        proc = subprocess.run(args, cwd=cwd, env=custom or env, capture_output=True, text=True, timeout=180)
        log.append(
            {
                "argv": list(map(str, args)),
                "status": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
        save(receipt / "worktree-commands.json", log)
        need(proc.returncode == want, (args, proc.returncode, proc.stderr[-600:]))
        return proc.stdout

    def git(*args, place=donor):
        return command(
            [
                "git",
                "-c",
                "user.name=Ohm native smoke",
                "-c",
                "user.email=qa@invalid.example",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            place,
        ).strip()

    need(
        "4a5f13b858c8d314ee3e8f639011f7ccefe71f97f96e50151fb991f267928e2c"
        in (donor / "Cargo.lock").read_text(),
        "wrong locked itoa",
    )
    crates = list(Path(env["CARGO_HOME"]).glob("registry/cache/*/itoa-1.0.15.crate"))
    need(
        len(crates) == 1
        and sha(crates[0]) == "4a5f13b858c8d314ee3e8f639011f7ccefe71f97f96e50151fb991f267928e2c",
        "wrong authentic registry artifact",
    )
    git("init", "--quiet", "-b", "smoke-parent")
    git("add", "Cargo.toml", "Cargo.lock", "src/main.rs")
    git("commit", "--quiet", "-m", "Original real package")
    head = git("rev-parse", "HEAD")
    target = smoke / "qa-child-target"
    command(cli + ["worktree", "add", "--detach", str(child), "--target-dir", str(target), head])
    need(
        git("rev-parse", "HEAD", place=child) == head and (child / ".git").is_file(),
        "not a linked Git worktree",
    )
    common = lambda d: Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", place=d)).resolve()
    need(common(child) == common(donor), "wrong common repository")
    child_env = env | {"CARGO_TARGET_DIR": str(target)}
    for value in (42, 73):
        if value == 73:
            f = child / "src/main.rs"
            old = f.read_text()
            need(old.count("format(42)") == 1, "unexpected original")
            f.write_text(old.replace("format(42)", "format(73)"))
        stream = command(cli + ["build", "--locked", "--offline", "--message-format=json"], child, child_env)
        rows = [json.loads(l) for l in stream.splitlines()]
        need(rows[-1] == {"reason": "build-finished", "success": True}, "incomplete child build")
        (itoa,) = [
            m for m in rows if m.get("reason") == "compiler-artifact" and m["target"]["name"] == "itoa"
        ]
        need(
            itoa["fresh"] and all(Path(f).is_file() for f in itoa["filenames"]),
            "workspace did not reuse real expected registry artifact",
        )
        (exe,) = [Path(m["executable"]) for m in rows if m.get("executable")]
        need(
            exe.is_relative_to(target) and command([exe], child, child_env).strip() == str(value),
            "wrong native child",
        )
    need(
        command([smoke / "registry-target/debug/ohm-registry-smoke"]).strip() == "42", "parent output changed"
    )
    f = child / "src/main.rs"
    f.write_text(f.read_text().replace("format(73)", 'format("invalid-integer")'))
    wrong = command(cli + ["check", "--locked", "--offline", "--message-format=json"], child, child_env, 101)
    diag = [json.loads(l) for l in wrong.splitlines()]
    need(
        any(
            m.get("message", {}).get("code")
            and m["message"]["code"]["code"] == "E0277"
            and any(s["is_primary"] and s["file_name"] == "src/main.rs" for s in m["message"]["spans"])
            for m in diag
        ),
        "wrong compiler diagnostic",
    )
    save(
        receipt / "worktree.json",
        {
            "head": head,
            "common_repository": str(common(donor)),
            "parent": 42,
            "child": [42, 73],
            "wrong_type": "E0277",
            "restored_registry_sha256": sha(crates[0]),
        },
    )


if __name__ == "__main__":
    main()
