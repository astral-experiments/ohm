"""Run the exact complete smoke, preserving a separate residual if line 68 rejects."""

import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, HERE, locations, need, save, sha

GATE = '  bash "$(dirname -- "${BASH_SOURCE[0]}")/smoke-test-relink.sh" "$OHM_TOOLCHAIN" "$smoke_root/relink"'
AFTER = '  sh "$RELEASE_DIRECTORY/ohm-installer.sh"\n'
SWAP = '"$OHM_QA_PY" -IB "$OHM_QA_TOOLS/installed.py" swap "$toolchain_root"\n'


def stage(source, helper, folder, role, residual):
    need(
        role in ("packaged", "fourfix", "static-fourfix")
        and sha(source) == CFG["outer_sha256"]
        and sha(helper) == CFG["helper_sha256"],
        "unregistered checked-in shell",
    )
    if role == "packaged" and not residual:
        return source
    folder.mkdir()
    code = source.read_text()
    need(code.count(GATE) == code.count(AFTER) == 1, "ambiguous script splice")
    if role in ("fourfix", "static-fourfix"):
        code = code.replace(AFTER, AFTER + SWAP)
    if residual:
        code = code.replace(
            GATE, '  printf "%s\\n" "The separate rejected relink gate is retained in full/."'
        )
    out = folder / source.name
    out.write_text(code)
    shutil.copyfile(helper, folder / helper.name)
    return out


def stopped_at_link(trace, outer):
    # Only a real failure of the separately qualified line may start the residual.
    # Shell command-substitution prefixes and the original cleanup trap are explicit.
    rows = []
    regex = r"^\++QA " + re.escape(str(outer)) + r":([0-9]+): (.*)$"
    for line in trace.decode(errors="replace").splitlines():
        m = re.match(regex, line)
        if m:
            rows.append((int(m[1]), m[2]))
    if rows and re.fullmatch(r"rm -rf .*/ohm-smoke\.[^/]+", rows[-1][1]):
        rows.pop()
    return bool(
        rows and re.fullmatch(r"bash .*/smoke-test-relink\.sh ohm-1\.99\.0-22 .*/relink", rows[-1][1])
    )


def main():
    root, target = locations()
    role = sys.argv[1]
    need(
        role in ("packaged", "fourfix", "static-fourfix") and shutil.disk_usage(root).free > 8 << 30,
        "private smoke volume needs 8 GiB free",
    )
    src = HERE.parent / "smoke-test-release.sh"
    sub = HERE.parent / "smoke-test-relink.sh"
    rbase = root / "receipts" / role
    rbase.mkdir()
    session = root / "sessions" / role
    session.mkdir(parents=True)
    analyzer = Path((root / "stock-analyzer.path").read_text().strip())
    stock = json.loads((root / "receipts/upstream.json").read_bytes())
    need(sha(analyzer) == stock["binary_sha256"], "wrong stock analyzer")
    env = {
        k: os.environ[k]
        for k in (
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "LANG",
            "LC_ALL",
            "DEVELOPER_DIR",
            "SDKROOT",
            "MACOSX_DEPLOYMENT_TARGET",
            "SYSTEM_VERSION_COMPAT",
            "COMMAND_MODE",
        )
        if k in os.environ
    }
    env.update(
        RUNNER_TEMP=str(session),
        TMPDIR=str(session),
        RUST_ANALYZER=str(analyzer),
        RUSTUP_AUTO_INSTALL="0",
        OHM_QA_TARGET=target,
        OHM_QA_ROLE=role,
        OHM_QA_PY=sys.executable,
        OHM_QA_TOOLS=str(HERE),
    )
    codes = {}
    for case in ["full", "residual"]:
        rdir = rbase / case
        rdir.mkdir()
        file = stage(src, sub, session / (case + "-scripts"), role, case == "residual")
        save(
            rdir / "launch.json",
            {
                "role": role,
                "case": case,
                "outer": sha(file),
                "original_outer": sha(src),
                "helper": sha(sub),
                "target": target,
                "analyzer": stock["binary_sha256"],
            },
        )
        with (rdir / "stdout.log").open("wb") as stdout, (rdir / "stderr.log").open("wb") as stderr:
            proc = subprocess.run(
                ["bash", HERE / "drive.sh", file, root / "release"],
                stdout=stdout,
                stderr=stderr,
                cwd=session,
                env=env | {"OHM_QA_RECEIPTS": str(rdir)},
            )
        raw = rdir / "commands.raw"
        trace = raw.read_bytes() if raw.exists() else b""
        # Apple's system Bash 3.2 has no BASH_XTRACEFD and writes PS4 to stderr.
        if not trace:
            trace = b"".join(
                l + b"\n" for l in (rdir / "stderr.log").read_bytes().splitlines() if re.match(rb"^\++QA ", l)
            )
            raw.write_bytes(trace)
        codes[case] = proc.returncode
        rejected = bool(proc.returncode and stopped_at_link(trace, file))
        for path in [raw, rdir / "stdout.log", rdir / "stderr.log"]:
            if path.exists():
                path.with_suffix(path.suffix + ".gz").write_bytes(gzip.compress(path.read_bytes(), mtime=0))
                path.unlink()
        save(rdir / "terminal.json", {"exit": proc.returncode, "observed_link_gate_failure": rejected})
        print(role, case, "returned", proc.returncode, "original relink refusal", rejected, flush=True)
        if case == "residual" or not rejected:
            break
    save(rbase / "outcome.json", {"role": role, "statuses": codes})
    if any(codes.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
