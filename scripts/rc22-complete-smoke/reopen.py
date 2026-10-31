"""Read both completed arms without an installed SDK or network."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, HERE, archive_origin, need, save


def load(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expected_outer(role):
    code = (HERE.parent / "smoke-test-release.sh").read_bytes()
    need(digest(code) == CFG["outer_sha256"], "unexpected original release shell")
    if role in ("fourfix", "static-fourfix"):
        install = b'  sh "$RELEASE_DIRECTORY/ohm-installer.sh"\n'
        need(code.count(install) == 1, "no unique installer")
        code = code.replace(
            install, install + b'"$OHM_QA_PY" -IB "$OHM_QA_TOOLS/installed.py" swap "$toolchain_root"\n'
        )
    return digest(code)


def observed(trace, target):
    records = []
    for line in trace.splitlines():
        m = re.match(r"^\++QA ([^:]+/smoke-test-release\.sh):\d+: (.+)$", line)
        if not m:
            continue
        try:
            args = shlex.split(m[2])
        except ValueError:
            # Entire multi-line quoted jq/awk programs are not observations here.
            continue
        if args:
            records.append([Path(args[0]).name, *args[1:]])

    def require(name, *parts, tail=None):
        need(
            any(
                a[0] == name
                and all(p in a[1:] for p in parts)
                and (tail is None or any(w.endswith(tail) for w in a[1:]))
                for a in records
            ),
            ("missing original shell observation", name, *parts, tail),
        )

    tag = "+" + CFG["release"]
    require("sh", tail="/ohm-installer.sh")
    require("bash", CFG["release"], tail="/smoke-test-relink.sh")
    require("rustdoc", tag, "--version")
    for t in ("cargo-clippy", "clippy-driver", "rustfmt", "cargo-fmt"):
        require(t, "--version")
    require("cargo", tag, "-Zohm-defaults=no", "build")
    require("cargo", tag, "build", "--target", "wasm32-unknown-unknown")
    require("python3", "-", tail="/ohm-smoke.wasm")
    require("cargo", tag, "clippy", "--", "-D", "warnings")
    require("cargo", tag, "doc", "--no-deps")
    require("cargo", tag, "fmt", "--", "--check")
    require(
        "env",
        "-u",
        "RUST_SRC_PATH",
        "RUSTUP_TOOLCHAIN=" + CFG["release"],
        "diagnostics",
        tail="/rust-analyzer",
    )
    for op in ("build", "check"):
        require("cargo", tag, op, "--offline", "--locked", tail="/registry-sibling/Cargo.toml")
    require("find", "-name", ".ohm-worktree-seed-deny-v7")
    if target == "x86_64-unknown-linux-gnu":
        require("ldd", tail="/toolchain/bin/cargo")
        for linker in ("lld", "wild"):
            for op in ("run", "test"):
                require("cargo", tag, "-Zohm-linker=" + linker, op)
        require("readelf", "--string-dump=.comment", tail="/linker-target/debug/ohm-smoke")
    else:
        require("otool", "-L", tail="/toolchain/bin/cargo")
    return len(records)


def complete(arm, role, catalog, target, analyzer, *, native_static_digest=None):
    root = arm / "full"
    need(
        load(arm / "outcome.json") == {"role": role, "statuses": {"full": 0}}
        and load(root / "terminal.json") == {"exit": 0, "observed_link_gate_failure": False}
        and (root / "release-shell.exit").read_bytes() == b"0\n"
        and not (arm / "residual").exists(),
        "partial or refused smoke",
    )
    need(
        load(root / "launch.json")
        == {
            "role": role,
            "case": "full",
            "outer": expected_outer(role),
            "original_outer": CFG["outer_sha256"],
            "helper": CFG["helper_sha256"],
            "target": target,
            "analyzer": analyzer,
        },
        "source bindings changed",
    )
    installed = load(root / "installed.json")
    original_files = {n: row[1] for n, row in catalog.items()}
    expected = dict(original_files)
    if role in ("fourfix", "static-fourfix"):
        if role == "static-fourfix":
            need(
                target == "x86_64-unknown-linux-gnu"
                and native_static_digest
                and re.fullmatch("[0-9a-f]{64}", native_static_digest),
                "missing static Cargo",
            )
            expected["bin/cargo"] = native_static_digest
        else:
            expected["bin/cargo"] = CFG["targets"][target]["fourfix_sha256"]
        need(
            load(root / "before-swap.json")["actual"] == original_files
            and load(root / "after-swap.json") == installed
            and expected != original_files,
            "swap not isolated",
        )
    else:
        need(not any(root.glob("*-swap.json")), "original installation was substituted")
    need(installed["role"] == role and installed["actual"] == expected, "different installed component")
    for name, rev in [
        ("rustc", CFG["rust"]),
        ("cargo", CFG["cargo"] if role == "packaged" else CFG["fourfix"]),
    ]:
        need(
            "commit-hash: " + rev in installed["versions"][name].splitlines()
            and "host: " + target in installed["versions"][name].splitlines(),
            "installed provenance",
        )
    payload = load(root / "payloads.json")
    keys = {"wasm", "native", "disabled_native", "documentation", "shared_registry_cli"}
    need(
        set(payload["bytes"]) == set(payload["sha256"]) == keys
        and all(
            payload["bytes"][k] > 8 and re.fullmatch(r"[0-9a-f]{64}", payload["sha256"][k]) for k in keys
        ),
        "missing native, wasm, docs or shared outputs",
    )
    if target.startswith("x86_64"):
        need(
            all("wild" in payload[k].lower() for k in ["default_elf_comment", "last_explicit_elf_comment"]),
            "Wild object note missing",
        )
    num = observed(gzip.decompress((root / "commands.raw.gz").read_bytes()).decode(), target)
    wt = load(root / "worktree.json")
    need(
        wt["child"] == [42, 73]
        and wt["parent"] == 42
        and wt["wrong_type"] == "E0277"
        and wt["restored_registry_sha256"]
        == "4a5f13b858c8d314ee3e8f639011f7ccefe71f97f96e50151fb991f267928e2c",
        "worktree or native verdict altered",
    )
    events = load(root / "worktree-commands.json")
    need(
        any(
            e["argv"][:4] == ["cargo", "+" + CFG["release"], "worktree", "add"] and e["status"] == 0
            for e in events
        ),
        "linked Git worktree was not created",
    )
    failures = [e for e in events if e["status"]]
    need(
        len(failures) == 1
        and failures[0]["status"] == 101
        and "check" in failures[0]["argv"]
        and any(
            m.get("message", {}).get("code")
            and m["message"]["code"]["code"] == "E0277"
            and any(s["is_primary"] and s["file_name"] == "src/main.rs" for s in m["message"]["spans"])
            for m in map(json.loads, failures[0]["stdout"].splitlines())
        ),
        "missing real invalid diagnostic",
    )
    return {
        "shell_commands_seen": num,
        "installed_records": len(expected),
        "cargo_sha256": expected["bin/cargo"],
        "payloads": payload["sha256"],
        "parent": wt["parent"],
        "child": wt["child"],
        "diagnostic": wt["wrong_type"],
    }


def review(root, local=False):
    release = load(root / "release.json")
    target = release["provenance"]["target"]
    arm = CFG["targets"][target]
    need(
        release["global"] == CFG["global"]
        and release["platform"] == arm["platform"]
        and all(release["sources"][k] == CFG[k] for k in ("rust", "cargo", "clippy")),
        "release origin",
    )
    for name, h in release["verified_leaves"].items():
        ref = CFG["checksums"].get(name, CFG["global_files"].get(name))
        if ref:
            need(h == ref, "wrong global or platform file")
    fix = load(root / "fourfix.json")
    need(
        fix["original"] == arm["native"]
        and fix["member"]["sha256"] == arm["fourfix_sha256"]
        and fix["cargo"]["tree"] == CFG["fourfix_tree"]
        and fix["cargo"]["commit"] == CFG["fourfix"],
        "private Cargo origin",
    )
    stock = load(root / "upstream.json")
    need(
        stock["channel_sha256"] == CFG["upstream"]["channel_sha256"]
        and stock["archive_sha256"] == arm["analyzer"]["xz_hash"]
        and stock["binary_bytes"] > 0
        and bool(stock.get("local_rehearsal")) == local,
        "upstream component",
    )
    if not local:
        need(
            stock["version"].startswith("rust-analyzer 1.99.0 ")
            and "host: " + target in stock["rustc"].splitlines(),
            "wrong stock executable",
        )
        for spec, step in [
            (CFG["global"], "Retain global release assets"),
            (arm["platform"], "Retain distribution artifacts"),
            (arm["native"], "Publish reusable native SDK"),
        ]:
            doc = load(root / f"official-{spec['artifact']}.json")
            archive_origin(spec, doc["run"], doc["job"], doc["artifact"], step)
    catalog = load(root / "archive-binaries.json")
    need(
        {"bin/rustc", "bin/cargo", "bin/cargo-clippy", "bin/clippy-driver", "bin/rustfmt", "bin/cargo-fmt"}
        <= catalog.keys()
        and any(p.startswith("lib/rustlib/wasm32-unknown-unknown/lib/libstd-") for p in catalog),
        "archive catalog",
    )
    return {
        "schema": 1,
        "target": target,
        "original_run": CFG["global"]["run"],
        "local": local,
        "roles": {
            r: complete(root / r, r, catalog, target, stock["binary_sha256"]) for r in ("packaged", "fourfix")
        },
    }


if __name__ == "__main__":
    need(
        len(sys.argv) in (2, 3) and (len(sys.argv) == 2 or sys.argv[2] == "--local"),
        "usage: reopen.py RECEIPTS [--local]",
    )
    root = Path(sys.argv[1])
    report = review(root, len(sys.argv) == 3)
    save(root / "verified.json", report)
    print(json.dumps(report, sort_keys=True))
