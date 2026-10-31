"""Read the successor independently, keeping the previous full-shell and worktree outcomes separate."""

import gzip
import hashlib
import tempfile
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import CFG, need, save, sha
from prior import project
from reopen import complete, load
from static_cargo import GNU, verify_product, releases, archive_identity


def worktree(files):
    proof = load(files / "worktree.json")
    owners = load(files / "worktree-registry.json")
    need(
        proof["child"] == [42, 73]
        and proof["parent"] == 42
        and proof["wrong_type"] == "E0277"
        and len(proof["shared_itoa"]) == len(proof["observed_identities"]) == 2
        and all(
            bool(row)
            and set(row) == visit.keys()
            and all(
                f in owners["parent_assets"]
                and visit[f] == owners["parent_assets"][f]
                and len(visit[f]) == 4
                and all(int(k) > 0 for k in visit[f][:3])
                and len(visit[f][3]) == 64
                for f in row
            )
            for row, visit in zip(proof["shared_itoa"], proof["observed_identities"], strict=True)
        )
        and owners["PATH"].endswith(":/usr/bin:/bin")
        and len(owners["PATH"].split(":")) == 3,
        "different linked checkout or shared file",
    )
    events = load(files / "worktree-commands.json")
    outputs = [x["stdout"].strip() for x in events if len(x["argv"]) == 1 and x["status"] == 0]
    need(outputs == ["42", "73", "42"], "missing real native execution of linked checkout and parent")
    builds = [e for e in events if e["argv"][:3] == ["cargo", "+" + CFG["release"], "build"]]
    need(len(builds) == 2 and all(e["status"] == 0 for e in builds), "wrong successful builds")
    for e, expected in zip(builds, proof["shared_itoa"], strict=True):
        (r,) = [
            r for r in map(json.loads, e["stdout"].splitlines()) if r.get("target", {}).get("name") == "itoa"
        ]
        need(r["fresh"] and r["filenames"] == expected, "stale child worktree")
    last = events[-1]
    need(
        last["argv"][:3] == ["cargo", "+" + CFG["release"], "check"]
        and last["status"] == 101
        and any(
            r.get("message", {}).get("code")
            and r["message"]["code"]["code"] == "E0277"
            and any(s["is_primary"] and s["file_name"] == "src/main.rs" for s in r["message"]["spans"])
            for r in map(json.loads, last["stdout"].splitlines())
        ),
        "wrong typed negative",
    )
    return {
        "native_outputs": outputs,
        "type_error": "E0277",
        "shared_paths": proof["shared_itoa"],
        "PATH": owners["PATH"],
    }


def read(receipts):
    target = load(receipts / "enrollment.json")["OHM_QA_TARGET"]
    prior = project(receipts / "previous-qa.zip", target)
    need(load(receipts / "previous-qa.json") == prior, "earlier completed shell lost")
    original = load(receipts / "release.json")
    need(
        original["platform"] == CFG["targets"][target]["platform"]
        and original["global"] == CFG["global"]
        and original["sources"]["cargo"] == CFG["cargo"]
        and original["sources"]["rust"] == CFG["rust"],
        "wrong distribution",
    )
    catalog = load(receipts / "archive-binaries.json")
    originals = {p: v[1] for p, v in catalog.items()}
    if target == GNU:
        p = verify_product(receipt=receipts / "static-product.json")
        src = load(receipts / "static-build/source.json")
        need(
            src["roles"]["fourfix"]["tree"] == CFG["fourfix_tree"]
            and src["roles"]["fourfix"]["mode_path_sha256_inventory"]
            == "383baa363424df9f5e03dac068ec23d1b27bb8eb099da2d98d8c7123e62b2d5b"
            and hashlib.sha256(
                json.dumps(
                    load(receipts / "static-build/locked-crates.json"), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            == "c44f2f1acb79c473ecdf6ead7a86a908a38420908477cd0f42595d424f7e6b77",
            "no complete compiler sources",
        )
        rows = [
            json.loads(s)
            for s in gzip.decompress((receipts / "static-build/cargo.stdout.gz").read_bytes()).splitlines()
        ]
        need(
            rows[-1] == {"reason": "build-finished", "success": True}
            and p["cargo_artifact"] in rows
            and p["static_archive"]["origin"] in rows,
            "wrong real build",
        )
        need(
            archive_identity(receipts / "static-build/libz.a")
            == {k: v for k, v in p["static_archive"].items() if k != "origin"},
            "archive did not reopen",
        )
        with tempfile.TemporaryDirectory() as temp:
            elf = Path(temp) / "cargo"
            with (
                elf.open("xb") as out,
                subprocess.Popen(
                    ["zstd", "-dcq", receipts / "static-cargo.zst"], stdout=subprocess.PIPE
                ) as z,
            ):
                while chunk := z.stdout.read(1 << 20):
                    need(out.tell() + len(chunk) <= p["bytes"], "oversized Cargo")
                    out.write(chunk)
                need(z.wait() == 0 and out.tell() == p["bytes"], "incomplete private GNU ELF")
            need(
                sha(elf) == p["sha256"]
                and releases(subprocess.check_output(["readelf", "-dW", elf], text=True), p["ldd"])
                == p["needed"],
                "wrong private GNU ELF or linkage",
            )
        a = complete(
            receipts / "static-fourfix",
            "static-fourfix",
            catalog,
            target,
            load(receipts / "upstream.json")["binary_sha256"],
            native_static_digest=p["sha256"],
        )
        return {
            "prior": prior,
            "static_product": p["sha256"],
            "full": a,
            "worktree": worktree(receipts / "static-fourfix/full"),
        }
    roles = {}
    for role in ["packaged", "fourfix"]:
        f = receipts / role / "focus"
        expect = dict(originals)
        need(
            load(f / "terminal.json")
            == {"role": role, "exit": 0, "scope": "one real parent and one linked checkout"}
            and load(f / "original-install.json")["actual"] == originals,
            "original install",
        )
        if role == "fourfix":
            expect["bin/cargo"] = CFG["targets"][target]["fourfix_sha256"]
            need(
                load(f / "before-swap.json")["actual"] == originals
                and load(f / "after-swap.json")["actual"] == expect,
                "wrong replacement",
            )
        need(load(f / "installed.json")["actual"] == expect, "different installed compiler")
        p = load(f / "parent.json")
        w = worktree(f)
        rows = [json.loads(l) for l in gzip.decompress((f / "parent-stdout.gz").read_bytes()).splitlines()]
        (itoa,) = [r for r in rows if r.get("target", {}).get("name") == "itoa"]
        need(
            p["PATH"] == w["PATH"]
            and p["executed"] == 42
            and not itoa["fresh"]
            and set(itoa["filenames"]) == p["registry_owners"].keys()
            and all(set(row) <= p["registry_owners"].keys() for row in w["shared_paths"])
            and all(
                p["registry_owners"][path] == identity[3]
                for path, identity in load(f / "worktree-registry.json")["parent_assets"].items()
                if path in p["registry_owners"]
            ),
            "parent and child actual registry or PATH differ",
        )
        roles[role] = w | {"cargo": expect["bin/cargo"]}
    return {"prior": prior, "worktree_only": roles}


if __name__ == "__main__":
    receipts = Path(sys.argv[1])
    report = read(receipts)
    save(receipts / "supplement-verified.json", report)
    print(json.dumps(report, sort_keys=True))
