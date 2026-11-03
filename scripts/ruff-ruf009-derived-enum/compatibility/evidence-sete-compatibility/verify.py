"""Reopen each original once, with its own enrolled source and physical SDK identity."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
spec = importlib.util.spec_from_file_location("raw", CASE / "evidence-41613048377/verify.py")
raw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(raw)


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--b3sum", required=True)
    args.add_argument("--out", type=Path, required=True)
    a = args.parse_args()
    plan = raw.read(CASE / "matrix/registration.json")
    assert {k:v["source"] for k,v in plan["roles"].items()} == {
        "P3":"dad5fae340339ea631fdafc3ef27956df1ffb81a", "Q3":"e157d8912adcdae91bd43df88959f3a510bfa34a"}
    result = {"actual_cargo_commands":182,"roles":plan["roles"],"client":plan["clients"]["current"],
              "first_refusal":"old Q2 identity before parked work","literal":{},"aliases":{}}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for label, expected in (("literal","01c56b24d7ddff6c9b7b472b41e5994feb65d426eb8ae081e62e293311624b8b"),
                                ("remaining","37c6e0cc77337855a9d4bc0c28dfc21e9c5ed446625e98f549c9d1dddd8cfc63")):
            dest = root / label
            dest.mkdir()
            manifest = raw.extract(HERE / (label+"-original.zip"), dest, expected)
            result[label+"_archive"] = {"zip":expected,"raw":manifest["sha256"],"files":len(manifest["files"])}
        first = root / "literal/matrix"
        second = root / "remaining/matrix"
        assert not (first/"parked-matched/visits").exists() and not (first/"complete.json").exists()
        for mode in ("legacy","aware","aware-registry"):
            label = "literal-"+mode
            actual = first/label
            record = raw.read(first/"dispatch"/(label+".json"))
            argv = record["command"]
            assert record["exit"] == 0
            new = root/(label+".json")
            subprocess.run([sys.executable,"-IB",CASE/"reopen.py","--root",actual,"--recorded-root",argv[argv.index("--work")+1],
                            "--b3sum",a.b3sum,"--output",new,"--expect","legacy" if mode=="legacy" else "aware"],check=True,stdout=subprocess.DEVNULL)
            assert raw.sha(actual/"independent.json") == raw.sha(new)
            data = raw.read(new)
            assert data["commands"]==40 and data["kernel_typed_rustcs"]==24 and data["binary_fingerprint_epoch"]==(4 if mode=="legacy" else 5)
            result["literal"][mode] = {k:data[k] for k in ("commands","kernel_typed_rustcs","terminal_sha256","binary_fingerprint_epoch")}
        terminal = raw.read(second/"complete.json")
        controls = {r["label"]:r for r in terminal["completed"]}
        assert set(controls)=={"parked-matched","literal-alias-P3","literal-alias-Q3"}
        bound = set()
        sdk = raw.read(root/"remaining/source-receipts/scope-kit-current.json")
        for arm in sdk["manifest"]["arms"].values(): bound.update(arm["files"].values())
        for label,s in plan["clients"].items():
            inv=raw.read(root/"remaining/source-receipts"/(label+"-cargo.json"))
            assert inv["actual"]==inv["source"]["binary"]==s["binary"] and s["source"] in inv["identity"]
            bound.add(s["binary"])
        assert {r["driver"]for r in plan["roles"].values()}|{plan["signed_cargo"],plan["wild"]} <= bound
        members=root/"members.json";members.write_text(json.dumps(sorted(bound)))
        parked=second/"parked-matched"
        subprocess.run([sys.executable,"-IB",CASE/"independent.py",parked,members],check=True,stdout=subprocess.DEVNULL)
        proof = raw.read(parked/"independent.json")
        assert raw.sha(parked/"independent.json") == controls["parked-matched"]["independent"] and len(proof["visits"]) == 44
        result["parked"] = {"commands":44,"kernel_rustcs":sum(len(v["typed"])for v in proof["visits"]),
                            "native":proof["native"],"receipt":raw.sha(parked/"independent.json")}
        for role in ("P3","Q3"):
            name = "literal-alias-"+role
            assert raw.sha(second/name/"complete.json")==controls[name]["complete"]
            result["aliases"][role]=raw.aliases(second/name,plan,a.b3sum)
        result["remaining_terminal"] = raw.sha(second/"complete.json")
    a.out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(result["actual_cargo_commands"],raw.sha(a.out))


if __name__=="__main__":
    main()
