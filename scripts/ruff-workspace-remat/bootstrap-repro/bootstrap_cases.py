import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

work = Path.cwd()
config = json.loads((work / "inputs.json").read_text())
rust_tree = Path(config["rust"])
revision_sha = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
host = "x86_64-unknown-linux-gnu"
originals = Path(config["sources"])
names = ("RegisterCoalescer.cpp", "RegisterCoalescer.h")
header = Path(config["llvm"]) / "include/llvm/Support/VCSRevision.h"
assert revision_sha in header.read_text()
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
results = {}


def run_case(
    name,
    mode="offline",
    action="optional",
    expect=None,
    expected_exit=0,
    local=False,
    cache_id=None,
    revision=True,
):
    base = work / "cases" / (cache_id or name)
    base.mkdir(parents=True, exist_ok=True)
    tools = base / ("tools-" + name)
    tools.mkdir()
    record = base / ("curl-log-" + name)
    out = base / "out"
    source = base / "source"
    source.mkdir(exist_ok=True)
    llvm = out / host / "ci-llvm"
    revision_header = llvm / "include/llvm/Support/VCSRevision.h"
    revision_header.parent.mkdir(parents=True, exist_ok=True)
    if revision:
        shutil.copy2(header, revision_header)
    else:
        revision_header.write_text(
            '#define LLVM_REVISION R"(0000000000000000000000000000000000000000)"\n'
        )
    if local:
        local_sources = source / "src/llvm-project/llvm/lib/CodeGen"
        local_sources.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy2(originals / n, local_sources / n)
    for tool in (
        "git",
        "sh",
        "uname",
        "env",
        "readlink",
        "grep",
        "sed",
        "cut",
        "pwd",
        "dirname",
        "false",
        "true",
        "rustc",
    ):
        x = Path("/usr/bin") / tool
        if x.is_file():
            (tools / tool).symlink_to(x)
    if mode != "missing":
        curl = tools / "curl"
        curl.write_text("""#!/usr/bin/python3
import json,os,sys
from pathlib import Path
argv=sys.argv[1:];m=os.environ['OHM_QA_CURL']
with Path(os.environ['OHM_QA_CAPTURE']).open('a') as f:f.write(json.dumps(argv)+'\\n')
if argv==['-V']:print('curl 8.12.1 (x86_64-unknown-linux-gnu)');sys.exit(0)
if m=='offline':sys.exit(7)
prefix='https://raw.githubusercontent.com/rust-lang/llvm-project/1b9c0d5ff9bbe7634aead059efe6b11a7eeba145/llvm/lib/CodeGen/'
urls=[a for a in argv if a.startswith('https://')];assert len(urls)==1
name=urls[0].removeprefix(prefix);assert name in ('RegisterCoalescer.cpp','RegisterCoalescer.h'),urls
out=Path(argv[argv.index('--output')+1]);root=Path(os.environ['OHM_QA_OUT']);assert root in out.parents
if m=='wrong' or (m=='second_wrong' and name.endswith('.h')):out.write_bytes(b'unauthenticated fixture bytes')
else:
 assert m in ('good','second_wrong'),m
 out.write_bytes((Path(os.environ['OHM_QA_ORIGINAL'])/name).read_bytes())
""")
        curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tools),
        "CARGO_HOME": str(work / "cargo"),
        "OHM_QA_SOURCE": str(source),
        "OHM_QA_OUT": str(out),
        "OHM_QA_CURL": mode,
        "OHM_QA_MODE": action,
        "OHM_QA_CAPTURE": str(record),
        "OHM_QA_ORIGINAL": str(originals),
        "HOME": str(base),
    }
    cli = [
        "--src",
        str(rust_tree),
        "--build-dir",
        str(base / "initial-config-out"),
        "--config",
        str(work / "bootstrap.toml"),
        "check",
    ]
    child = subprocess.run(
        [work / "target/debug/bootstrap", *cli],
        cwd=base,
        env=env,
        check=False,
        timeout=10,
        capture_output=True,
    )
    cache = out / "cache/ohm-llvm-source" / revision_sha
    cached = sorted(x.name for x in cache.iterdir()) if cache.is_dir() else []
    body = child.stdout.decode()
    stderr = child.stderr.decode()
    calls = (
        [json.loads(x) for x in record.read_text().splitlines()]
        if record.exists()
        else []
    )
    downloads = [a for args in calls for a in args if a.startswith("https://")]
    expected = (
        None
        if action == "required"
        else "QA_SOURCES="
        + (
            "NONE"
            if expect is None
            else str(
                cache
                if expect == "cache"
                else source / "src/llvm-project/llvm/lib/CodeGen"
            )
        )
    )
    receipt = {
        "code": child.returncode,
        "expected": expected,
        "stdout": body,
        "stderr": stderr,
        "calls": calls,
        "urls": downloads,
        "cached": {n: sha(cache / n) for n in cached},
        "required_output": (out / "required").exists(),
    }
    results[name] = receipt
    (work / "bootstrap-cases.json").write_text(json.dumps(results, indent=2) + "\n")
    assert child.returncode == expected_exit and (
        expected is None or expected in body
    ), receipt
    return receipt


assert run_case("no-matching-revision", revision=False)["calls"] == []
assert run_case("refused")["cached"] == {}
assert len(results["refused"]["urls"]) == 1
assert run_case("missing-curl", mode="missing")["cached"] == {}
assert run_case("corrupt-response", mode="wrong")["cached"] == {}
assert len(results["corrupt-response"]["urls"]) == 1
assert run_case("partially-available", mode="second_wrong", cache_id="retry")[
    "cached"
] == {names[0]: sha(originals / names[0])}
goodset = {n: sha(originals / n) for n in names}
retry = run_case("retry-authenticated", mode="good", cache_id="retry", expect="cache")
assert retry["cached"] == goodset and [x.rsplit("/", 1)[-1] for x in retry["urls"]] == [
    names[1]
]
assert (
    run_case("cache-offline", mode="offline", cache_id="retry", expect="cache")["calls"]
    == []
)
local = run_case("matching-submodule", local=True, expect="local")
assert not local["calls"] and not local["cached"]
r = run_case("required-refused", action="required", expected_exit=1)
assert (
    r["urls"] == ["https://qa.invalid/required"]
    and not r["required_output"]
    and "QA_REQUIRED_COMPLETED" not in r["stdout"]
)
print("passed", len(results), "full bootstrap cases")
