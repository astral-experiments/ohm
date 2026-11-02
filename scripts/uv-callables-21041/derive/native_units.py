"""Resolve the compiler's native external DefIds from the exact Cargo and sysroot products that own them."""
from collections import defaultdict
from functools import cache
from hashlib import sha256
from pathlib import Path
import struct
import identity_wire as w


class NativeUnits:
    def __init__(self,targets,sysroot,workspace,archive=None):
        self.files=defaultdict(set)
        self.known={}
        self.used={}
        self.inspected=set()
        for directory in targets:
            for suffix in ("*.rmeta","*.so"):
                for path in directory.rglob(suffix):
                    self.files[path.name].add(path)
        if sysroot is not None:
            for path in (sysroot/"lib/rustlib/x86_64-unknown-linux-gnu/lib").glob("*.rmeta"):
                self.files[path.name].add(path)
        for name,paths in (archive or {}).items():
            self.files[name].update(paths)
        self.workspace=workspace
        for name,path in workspace.items():
            self.files[name].add(path)
    @cache
    def declarations(self,name,extra,public,macro):
        suffix=extra+(".so" if macro else ".rmeta")
        if isinstance(name,str):
            potential=self.files.get("lib"+name+suffix,set())
        else:
            assert name[0]=="preinterned" and not macro
            potential={p for filename,paths in self.files.items() if filename.endswith(suffix) for p in paths}
        matches=[]
        for path in sorted(potential):
            data=path.read_bytes()
            self.inspected.add(path)
            if macro:
                record=w.macro_elf(path)
                if record["public_hash"]!=public:continue
                assert record["name"]==name
                # Each registered proc macro is an exported MacroNs; preserve its symbol and slot.
                result={h:(("CrateRoot",None,0),("MacroNs",d["name"][1],d["disambiguator"])) for h,d in record["declarations"].items()}
                assert all(d["parent"]==record["root_local_hash"] for d in record["declarations"].values())
                assert len({d["parent"]for d in record["declarations"].values()})==1
                stable_id=record["stable_crate_id"]
            else:
                cname,_,own_public=w.hdr(data)
                if cname!=(name if isinstance(name,str) else name[1]) or own_public!=public:continue
                head,result=w.external_identity_rows(data)
                assert head["extra_filename"]==extra
                stable_id=head["stable_crate_id"]
            matches.append((sha256(data).hexdigest(),result,stable_id))
        assert matches,("no native declaration provider",name,extra,public,macro)
        a=matches[0]
        for b in matches[1:]:
            assert a[1:]==b[1:],("two genuinely different external DefKey tables",name,extra,public)
        self.used[(name,extra,public,macro)]=[sorted({x[0]for x in matches}),a[2],len(a[1])]
        return a[1]
