"""Independently derive all process sets, live mappings and object bytes from a parked-kit run."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

base = Path(sys.argv[1]).resolve(strict=True)
p = base / "proof"
read = lambda path: json.loads(path.read_bytes())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
reg = read(p / "registration.json")
product = read(p / "complete.json")
initial = read(p / "installed-before-any-typed-command.json")
dec = json.JSONDecoder()
assert reg["receiver_sha256"] == sha(Path(__file__).with_name("switch.py"))
assert product["registration"] == sha(p / "registration.json")
roles = {}
visits = []
wild = []
same = {}
for idx, (client, role) in enumerate(reg["switch_order"]):
    roles[f"{idx:02d}-{client}-{role}"] = (client, role)
roles["check-build"] = ("aware", "C")
for cel, (client, role) in roles.items():
    option = reg["option"] if client == "aware" else reg.get("secondary") if client == "fixed" else None
    expected_active = (role == "C" and client == "aware") or (role == "P" and client == "fixed" and "secondary" in reg)
    cell = p / cel
    names = (["build", "empty-build", "explicit-defaults-off", "workspace-wrapper"] if cel == "check-build"
             else ["old", "edit", "unchanged", "repair"])
    suite = {}
    for name in names:
        v = cell / name
        inv, obs = read(v / "invocation.json"), read(v / "observed.json")
        assert tuple(inv[k] for k in ("client", "role")) == (client, role)
        assert inv["driver"] == reg["driver"][role] == sha(base / "packs" / role / "driver")
        assert inv["cargo"] == reg[{"signed":"cargo", "fixed":"fixed_cargo_sha256","aware":"aware_cargo_sha256"}[client]] == sha(base / "packs" / client)
        assert inv["frontend"] == initial["frontend"] == product["frontend"] and obs["driver"] == initial["drivers"][role]
        assert sha(p / "objects" / obs["metadata_sha256"]) == obs["metadata_sha256"]
        assert (v / "metadata-header.txt").is_file()
        cargos, typed, probes, native, unlinks = [], {}, [], [], []
        lineage = {}
        for trace in v.glob("trace.*.gz"):
            tid = int(trace.name.split(".")[1])
            s = gzip.decompress(trace.read_bytes()).decode()
            for ln in s.splitlines():
                if ln.startswith(("clone(", "clone3(", "fork(", "vfork(")) and (m := re.search(r" = ([0-9]+)$", ln)):
                    lineage.setdefault(tid, []).append(int(m[1]))
                if ln.startswith(("unlink(", "unlinkat(")) and "/.ohm-check-graphs/" in ln and ln.endswith(" = 0"):
                    lineage.setdefault(tid, []).append("discard");unlinks.append(tid)
                if not ln.startswith("execve(") or not ln.endswith(" = 0"):continue
                exe,n=dec.raw_decode(ln[7:]);argv,_=dec.raw_decode(ln[7+n:].lstrip(", "))
                if exe==str(base/"rustup/toolchains/ohm/bin/cargo"):
                    assert argv[1:] == inv["argv"][2:];cargos.append(tid)
                if exe.endswith("/wild-ld/ld.bfd"):
                    native.append((exe, sha(Path(exe))))
                if exe!=str(base/"install/bin/rustc"):continue
                if "--crate-name" in argv and "--out-dir" in argv:
                    assert "--crate-name" in argv and tid not in typed
                    typed[tid]=(argv[argv.index("--crate-name")+1], argv)
                elif len(argv) == 3 and argv[1] in ("-Zohm-checked-private-derives","-Zohm-checked-private-derives-v2") and argv[2] == "--print=sysroot":
                    assert argv[1] == option;probes.append(tid)
                else:continue
                assert re.search(r"^mmap\(.*PROT_EXEC.*<"+re.escape(str(base/"install/lib"))+r"/librustc_driver-[^/<>]+\.so>.* = 0x[0-9a-f]+$",s,re.M)
        assert len(cargos)==1 and sorted(probes)==sorted(obs["probes"])
        assert native==[tuple(x) for x in obs["native"]] and all(sha==reg["wild"] for _,sha in native)
        assert typed=={r["pid"]:(r["crate"],r["argv"]) for r in obs["true"]}
        on=expected_active and name not in ("explicit-defaults-off","workspace-wrapper")
        for crate, argv in typed.values():
            assert set(argv).intersection({"-Zohm-checked-private-derives","-Zohm-checked-private-derives-v2"}) == ({option} if on and crate=="dep" else set())
        if option is not None and name not in ("explicit-defaults-off","workspace-wrapper"):
            assert 1<=len(probes)<=2
            if len(probes)==2:
                assert unlinks==cargos
                ev=[x for x in lineage[cargos[0]] if x=="discard" or x in probes]
                assert len(ev)==3 and ev[1]=="discard" and {ev[0],ev[2]}==set(probes)
        else:assert not probes
        arts=[json.loads(row) for row in (v/"stdout").read_text().splitlines()]
        assert arts[-1]=={"reason":"build-finished","success":True}
        targets=sorted(t[0] for t in typed.values())
        if name in ("edit","repair"):assert targets==(["dep"] if on else ["app","dep"])
        if name=="unchanged":assert not targets
        if name in ("build","empty-build"):
            assert native and targets and sha(p/"objects"/obs["elf"])==obs["elf"]
            assert (p/"objects"/obs["elf"]).read_bytes()[:4]==b"\x7fELF"
            wild.append([obs["elf"],obs["metadata_sha256"]])
        suite[name]=obs
        visits.append({"cell":cel,"visit":name,"probe_count":len(probes),"typed":targets,"linkers":len(native),"nominal":obs["nominal"],"meta_sha256":obs["metadata_sha256"]})
    if cel!="check-build":
        assert (suite["old"]["public"]==suite["edit"]["public"]) == (expected_active)
        assert suite["old"]["metadata_sha256"]==suite["repair"]["metadata_sha256"]!=suite["edit"]["metadata_sha256"]
        identity=tuple(suite["old"][k] for k in ("meta","metadata_sha256"))+(suite["edit"]["metadata_sha256"],)
        assert same.setdefault((role,client),identity)==identity
assert len(visits)==44 and len(wild)==2 and wild[0]==wild[1]==[product["native"],product["native_rmeta"]]
assert same["C","aware"][0]!=same["C","fixed"][0] and same["C","aware"][0]!=same["P","aware"][0]
out=base/"independent.json"
out.write_text(json.dumps({"terminal_sha256":sha(p/"complete.json"),"native":wild,"visits":visits},sort_keys=True,indent=1)+"\n")
print(len(visits),sum(len(v["typed"])for v in visits),sum(v["probe_count"]for v in visits),sha(out))
