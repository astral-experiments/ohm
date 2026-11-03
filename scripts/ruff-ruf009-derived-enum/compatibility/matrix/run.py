"""Qualify the v2 handshake and real consumed-input behavior on separately installed SDKs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
REG = json.loads((HERE / "registration.json").read_bytes())


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


def check(cmd, out):
    print("Running", out.stem, flush=True)
    with out.with_suffix(".stdout").open("xb") as stdout, out.with_suffix(".stderr").open("xb") as stderr:
        result = subprocess.run(cmd, stdout=stdout, stderr=stderr)
    write(out.with_suffix(".json"), {"command": list(map(str, cmd)), "exit": result.returncode})
    if result.returncode:
        print(out.with_suffix(".stderr").read_text()[-3000:], flush=True)
        result.check_returncode()


def space(path):
    available = int(next(s.split()[1] for s in Path("/proc/meminfo").read_text().splitlines() if s.startswith("MemAvailable:"))) * 1024
    return {"memory": available, "disk": shutil.disk_usage(path).free}


def spec(kind, p, c, client):
    template = read(CASE / ("parked.json" if kind == "parked" else "literal.json"))
    wanted = ["switch_order"] if kind == "parked" else ["argv", "histories", "phases", "roles"]
    reg = {k: template[k] for k in wanted}
    reg.update(P=REG["roles"][p]["source"], C=REG["roles"][c]["source"],
               driver={"P": REG["roles"][p]["driver"], "C": REG["roles"][c]["driver"]},
               cargo=REG["signed_cargo"], wild=REG["wild"], aware_cargo_sha256=REG["clients"][client]["binary"],
               fixed_cargo_sha256=REG["clients"]["fixed"]["binary"], option=REG["flags"][client],
               scope="Unscored real native compatibility", registration=sha(HERE / "registration.json"))
    if kind == "parked":
        reg["receiver_sha256"] = sha(CASE / "switch.py")
    return reg


def aliases(root, sdk, cargo, source, role):
    # Exercise the exact corrected writer, whose conflicting consumed file has no coherent digest.
    path = source / "replay.py"
    assert sha(path) == REG["alias_source"]
    mod_spec = importlib.util.spec_from_file_location("recorded_alias_replay", path)
    replay = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(replay)
    root.mkdir()
    replay.args = SimpleNamespace(root=root, c2=sdk)
    replay.DRIVERS["c2"] = REG["roles"][role]["driver"]
    replay.install("c2", cargo, REG["clients"]["current"]["binary"], True)
    wrong = root / "fixed-c2"
    replay.changed(wrong, "c2", 5)
    replay.run(wrong, "c2", "first-unchanged", 101, 1)
    replay.run(wrong, "c2", "independent-empty", 101, 1, clean=True)
    replay.repaired(wrong, "c2")
    good = root / "positive-c2"
    replay.seed(good, True)
    replay.run(good, "c2", "ordinary", 0, 1)
    replay.run(good, "c2", "ordinary-unchanged", 0, 0)
    write(root / "complete.json", {"role": role, "driver": replay.DRIVERS["c2"], "cargo": sha(cargo),
                                   "input_hashes": [replay.OLD_SUM, replay.NEW_SUM], "source": sha(path)})


def main():
    p = argparse.ArgumentParser()
    for name in ("root", "p3", "q3", "current", "fixed", "b3sum", "alias-source"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    root = a.root.resolve()
    root.mkdir(parents=False, exist_ok=False)
    logs = root / "dispatch"
    logs.mkdir()
    sdk = {name: getattr(a, name.lower()).resolve(strict=True) for name in REG["roles"]}
    clients = {name: getattr(a, name).resolve(strict=True) for name in REG["clients"]}
    for name, kit in sdk.items():
        assert sha(next((kit / "lib").glob("librustc_driver-*.so"))) == REG["roles"][name]["driver"]
        assert sha(kit / "bin/cargo") == REG["signed_cargo"]
    for name, cargo in clients.items():
        assert sha(cargo) == REG["clients"][name]["binary"]
    admissions = []
    for _ in range(3):
        avail = space(root)
        admissions.append(avail)
        assert avail["memory"] > 9.25*2**30 and avail["disk"] > 15*2**30, avail
        time.sleep(.1)
    write(logs / "enrollment.json", {"resources": admissions, "plan": sha(HERE / "registration.json"),
                                      "b3sum": sha(a.b3sum), "producer": sha(Path(__file__)),
                                      "programs": {n: sha(CASE / (n+".py")) for n in ("reproduce", "reopen", "switch", "independent")}})
    py = [sys.executable, "-IB"]
    completed = []
    for mode in REG["literal"]:
        label = "literal-" + mode
        if mode in REG["prior_literal_cells"]:
            frozen = REG["prior_literal_cells"][mode]
            report = HERE/"prior"/(mode+".json")
            proof = read(report)
            assert sha(report) == frozen["digest"] and proof["terminal_sha256"] == frozen["native_terminal"]
            assert proof["commands"] == 40 and proof["kernel_typed_rustcs"] == 24 and proof["binary_fingerprint_epoch"] == frozen["epoch"]
            completed.append({"label":label, "commands":40, "independent":sha(report), "original_acquisition":REG["prior_literal_source"]})
            continue
        contract = logs / (label+"-registration.json")
        write(contract, spec("literal", "P3", "Q3", "current"))
        expect = "legacy" if mode == "legacy" else "aware"
        argv = [*py, CASE/"reproduce.py", "--registration", contract, "--work", root/label,
                "--parent-sdk", sdk["P3"], "--candidate-sdk", sdk["Q3"], "--b3sum", a.b3sum, "--expect", expect]
        if expect == "aware":
            argv += ["--cargo", clients["current"], "--cargo-sha256", REG["clients"]["current"]["binary"]]
        if mode == "aware-registry":
            argv += ["--registry-outputs"]
        check(argv, logs / label)
        out = root/label/"independent.json"
        check([*py,CASE/"reopen.py", "--root",root/label,"--b3sum",a.b3sum,"--output",out,"--expect",expect],logs/(label+"-reopen"))
        h = read(out)
        assert h["commands"] == 40
        completed.append({"label": label, "commands": h["commands"], "independent": sha(out)})
    for label, p, c, flavor in REG["switches"]:
        both_active = label == "parked-both-active"
        label = "parked-" + label
        fixed_client = "early" if both_active else "fixed"
        contract = logs / (label+"-registration.json")
        cell = spec("parked", p, c, flavor)
        if both_active:
            cell.update(switch_order=REG["both_active_order"], secondary=REG["flags"]["early"], fixed_cargo_sha256=REG["clients"]["early"]["binary"])
        write(contract, cell)
        check([*py,CASE/"switch.py", "--registration",contract, "--work",root/label, "--parent-sdk",sdk[p],
               "--candidate-sdk",sdk[c],"--aware-cargo",clients[flavor],"--fixed-cargo",clients[fixed_client]], logs/label)
        check([*py,CASE/"independent.py",root/label],logs/(label+"-reopen"))
        out = root/label/"independent.json"
        assert len(read(out)["visits"]) == 44
        completed.append({"label": label, "commands": len(read(out)["visits"]), "independent": sha(out)})
    for role in REG["alias_roles"]:
        label = "literal-alias-"+role
        aliases(root/label, sdk[role], clients["current"], a.alias_source, role)
        completed.append({"label":label,"complete":sha(root/label/"complete.json")})
    write(root/"complete.json", {"registration":sha(HERE/"registration.json"), "enrollment":sha(logs/"enrollment.json"), "completed":completed})


if __name__ == "__main__":
    main()
