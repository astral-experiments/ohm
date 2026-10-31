"""Verify the original hosted ZIPs and replay their native observations with Python 3.10+."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
QA = "d1e77f9acf1bb19ceb72274b89a5aaa119fb8bf1"
ARCHIVES = {
    "bootstrap-observations-parent": (13025383979, 13405, "49da09c34d3a7db281b08b9f8c06349157a434bf636988e0f90c603222b64fd7"),
    "bootstrap-observations-candidate": (13026182708, 17019, "83ad4e7d8ec80bc10d58e2fe038e8f87a0c6968b188fe8711663914797eddd14"),
    "bootstrap-observations-legacy": (13025971773, 9521, "2289e92373c4969cfa8c49f41c8e677e41f64a6249147c2b542880dc4a6ea976"),
    "compiler-native-admission": (13025832165, 347121, "4bc925462bf00265f0943f609a252c9c898f355dca9535d3e6e1fc1f169473ff"),
}
TREES = {
    "parent": "77ad1e80afc956a830491544d43695ec699fac2e",
    "candidate": "0d30133a68ccfb5771670ef5fee7720e1483f5dc",
    "legacy": "d79f6d5052da7bf1d66b9bd67f57f0ecbbe57b05",
}
NATIVE = "x86_64-unknown-linux-gnu"
WILD = "lib/rustlib/" + NATIVE + "/bin/wild-ld/ld.bfd"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reopen(name):
    path = HERE / (name + ".zip")
    _, size, digest = ARCHIVES[name]
    require(path.stat().st_size == size and hashlib.sha256(path.read_bytes()).hexdigest() == digest, name)
    with ZipFile(path) as archive:
        members = {}
        for entry in archive.infolist():
            rel = Path(entry.filename)
            require(not rel.is_absolute() and ".." not in rel.parts and not stat.S_ISLNK(entry.external_attr >> 16), entry.filename)
            require(entry.filename not in members and not entry.is_dir(), entry.filename)
            members[entry.filename] = archive.read(entry)  # Also checks each ZIP CRC.
        return members


def stream(data):
    return [json.loads(line) for line in data.splitlines() if line.startswith(b"{")]


def inspect_role(data, role, summary):
    base = "receipts/" + role + "/"
    rows = {key[len(base):]: value for key, value in data.items() if key.startswith(base)}
    failures = {"metadata/" + tag: 1 for tag in ("cross-epoch", "untagged-user", "official-stock-rejected")}
    failures.update({"cargo/invalid/build": 101, "cargo/invalid-empty/build": 101})
    cmds = {key.removesuffix("/command.json"): json.loads(value) for key, value in rows.items() if key.endswith("/command.json")}
    require(len(cmds) == 126 and failures.keys() <= cmds.keys(), (role, "command inventory"))
    for case, cmd in cmds.items():
        require(cmd["status"] == failures.get(case, 0), (role, case, cmd["status"]))
        for output in ("stdout", "stderr"):
            require(case + "/" + output in rows, (case, output))
        serr = rows[case + "/stderr"]
        require(b"internal compiler error" not in serr.lower(), (role, case, "ICE"))
        if case.startswith("metadata/") and case in failures:
            errors = {item["code"]["code"] for item in stream(serr) if item.get("level") == "error" and item.get("code")}
            require("E0514" in errors, (role, case))
    for case in ("run-matched", "run-untagged"):
        require(rows["metadata/" + case + "/stdout"] == b"42\n", case)

    # Each record was extracted from the LLVM return instruction of a real function-pointer probe.
    no_provider = {"consumer-forces-no", "homogeneous-1", "other-direction", "producer-forces-no"}
    yes_provider = {"consumer-forces-yes", "homogeneous-0", "producer-forces-yes", "producer-no-ub"}
    for mode in ("no", "yes"):
        for case in no_provider | yes_provider | {"mixed", "repaired"}:
            enriched = case in {"mixed", "repaired"} and role == "candidate"
            key = mode + "/" + case
            actual = json.loads(rows[key + "/symbols.json"])
            expected = {"hinted": case not in no_provider and not enriched, "foreign": case not in no_provider, "never": True}
            require(actual == expected == summary["raw"][key], (role, key, actual))
            require(cmds[key + "/run"]["status"] == 0, (role, key, "native"))
    require(len(summary["raw"]) == 20, (role, "symbol cases"))
    for target in (NATIVE, "aarch64-unknown-linux-gnu", "custom-host"):
        value = json.loads(rows["target/" + target + "/symbol.json"])
        external = role == "parent" or target != NATIVE
        require(value["triple"] == (NATIVE if target == "custom-host" else target), target)
        require("hinted" in value["symbol"] and value["symbol"].endswith("8provider" if external else "8consumer"), (role, target, value))
        require(summary["targets"][target] == external, (role, target, external))

    all_checked = (True, True, True)
    for case in ("all", "p-nodebug", "c-nodebug", "p-nooverflow", "c-nooverflow", "p-noub", "c-noub"):
        provider, consumer = list(all_checked), list(all_checked)
        if case != "all":
            owner, flag = case.split("-")
            (provider if owner == "p" else consumer)[("nodebug", "nooverflow", "noub").index(flag)] = False
        expected = " ".join(str(tuple(x)).lower() for x in (provider, consumer, provider))
        require(rows["axes/" + case + "/run/stdout"].decode().strip() == expected == summary["axes"][case], (role, case))

    observed, diagnostics = {}, []
    good = {"initial", "repeat", "flip-o1", "empty-o1", "return-o0", "empty-o0", "edited", "edited-empty", "repaired", "repair-empty"}
    for case in sorted(good | {"invalid", "invalid-empty"}):
        root = "cargo/" + case
        lines = stream(rows[root + "/build/stdout"])
        require(lines[-1] == {"reason": "build-finished", "success": case in good}, (role, case))
        errors = [x["message"] for x in lines if x["reason"] == "compiler-message" and x["message"]["level"] == "error"]
        if case not in good:
            require(len(errors) == 1 and errors[0]["code"]["code"] == "E0308", (role, case))
            primary = [(s["file_name"], s["line_start"], s["column_start"]) for s in errors[0]["spans"] if s["is_primary"]]
            require(primary == [("provider/src/lib.rs", 13, 32)], primary)
            diagnostics.append(errors[0])
            continue
        require(not errors, (role, case))
        record = json.loads(rows[root + "/observation.json"])
        actual = {x["target"]["name"]: x["fresh"] for x in lines if x["reason"] == "compiler-artifact"}
        require(actual == record["fresh"] and set(actual) == {"consumer", "shared", "provider"}, (role, case))
        require(case != "repeat" or all(actual.values()), (role, "unchanged"))
        expected = "29" if case in {"edited", "edited-empty"} else "17"
        require(rows[root + "/run/stdout"].decode().strip() == expected == record["output"] == summary["cargo"][case], (role, case))
        observed[case] = record["elf"]
    for warm, empty in (("flip-o1", "empty-o1"), ("return-o0", "empty-o0"), ("edited", "edited-empty"), ("repaired", "repair-empty")):
        require(observed[warm] == observed[empty], (role, warm, empty))
    require(observed["initial"] == observed["repeat"] == observed["repaired"] != observed["edited"], role)
    require(diagnostics[0] == diagnostics[1], (role, "warm versus empty diagnostic"))
    return diagnostics[0], observed


def main():
    native = reopen("compiler-native-admission")
    verdict = json.loads(native["receipts/qualification.json"])
    require(verdict["status"] == "pass" and set(verdict["roles"]) == set(TREES), "roles")
    manifests = {}
    for role, tree in TREES.items():
        raw = reopen("bootstrap-observations-" + role)
        manifest = json.loads(raw["receipts/manifest.json"])
        require(manifest["qa"] == QA and manifest["tree"] == tree and manifest["role"] == role, (role, "source"))
        require({k: manifest[k] for k in ("commit", "tree", "metadata", "transfer")} == verdict["roles"][role], (role, "admission"))
        if role == "candidate":
            for file, name in (("metadata-unit", "rmeta::generic_export_flags_preserve_old_c_linker_bits"),
                               ("product-regression", "[run-make] tests/run-make/ohm-profile-aware-shared-generics")):
                log = raw["receipts/" + file + ".log"]
                require(("test " + name + " ... ok").encode() in log and b"1 passed; 0 failed" in log, name)
        manifests[role] = manifest
    require(manifests["parent"]["commit"] == "c79998a5cd143c445a4b2528f20953b176a65c5d", "signed source")
    for field in ("llvm", "stage0", "flags", "version"):
        require(all(m[field] == manifests["parent"][field] for m in manifests.values()), field)
    require(manifests["parent"]["files"]["bin/cargo"] == manifests["candidate"]["files"]["bin/cargo"], "Cargo")
    require(manifests["parent"]["files"][WILD] == manifests["candidate"]["files"][WILD], "Wild")
    require(manifests["parent"]["files"]["bin/cargo"][0] == "035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4", "Cargo image")
    require(manifests["parent"]["files"][WILD][0] == "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5", "Wild image")
    for case in ("release", "compile-self", "run-self"):
        require(json.loads(native["receipts/stock/" + case + "/command.json"])["status"] == 0, case)
    require(b"b940084d7eb6a299eb4bfeb8e34901bc051e7ac4" in native["receipts/stock/release/stdout"], "official stock")
    require(native["receipts/stock/run-self/stdout"] == b"stock=42\n", "stock executable")
    parent, candidate = (inspect_role(native, r, verdict["results"][r]) for r in ("parent", "candidate"))
    require(parent[0] == candidate[0], "cross-role structured diagnostic")
    require(verdict["results"]["parent"]["bare_export"] == verdict["results"]["candidate"]["bare_export"], "legacy exporter")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path, data in native.items():
            if path.startswith("incremental-transaction/"):
                dest = root / path.removeprefix("incremental-transaction/")
                dest.parent.mkdir(exist_ok=True, parents=True)
                dest.write_bytes(data)
        verifier = HERE.parents[1] / "verify_incremental.py"
        output = subprocess.check_output([sys.executable, "-IB", verifier, root])
        require(output == native["receipts/incremental/independent-reader/stdout"], "hosted and offline migration readback")
        transition = json.loads(output)
    print(json.dumps({"source_run": 41157899149, "source_head": QA, "source_trees": TREES,
                      "native_commands_per_arm": 126, "mixed_hinted_ownership": ["provider", "consumer"],
                      "cargo_malformed": "E0308 at provider/src/lib.rs:13:32", "elf_hashes": {"parent": parent[1], "candidate": candidate[1]},
                      "migration": transition}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
