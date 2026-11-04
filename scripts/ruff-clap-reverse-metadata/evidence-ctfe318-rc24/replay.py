"""Recheck original metadata and the complete marginal process stream in the permanent compact packet."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
import companion
import verify

class Role:
    def __init__(self,archive,role):
        self.archive=archive
        self.prefix=role+"/"
    def read(self,name):
        return self.archive.read(self.prefix+name)
    def getinfo(self,name):
        return self.archive.getinfo(self.prefix+name)

def reopen():
    packet=here/"physical-probes-and-metadata.zip"
    with packet.open("rb") as stream:
        assert hashlib.file_digest(stream,"sha256").hexdigest()=="91c976536e66bd92bbe2fab6a4a3df4a3bf447ef77f70359eaae9b1b590e8dc0"
    receipt=json.loads((here/"verified.json").read_bytes())
    verdict={}
    with zipfile.ZipFile(packet) as raw:
        assert len(raw.namelist())==len(set(raw.namelist()))==668
        for role in "PC":
            obj=verify.Original(Role(raw,role),role,None)
            version=obj.record("factory/sdk.json")["versions"]["rustc"]
            assert receipt[role]["source"] in version and obj.record("registration.json")["driver"]==receipt[role]["driver"]==verify.SDK[role]["driver"]
            verify.metadata.ver=version.splitlines()[0]+" (Ohm metadata 3)"
            for crate in ("ruff","ruff_dev"):
                prefix="normal-"+crate+"/"
                previous=obj.selected(prefix+"initial-consumer",False)
                edited=obj.selected(prefix+"producer-NEW",True)
                repair=obj.selected(prefix+"producer-REPAIR",True)
                restored=obj.selected(prefix+"producer-OLD",False)
                current=obj.selected(prefix+"unchanged-consumer",False)
                assert restored==current and previous[1][0]["public"]!=edited[1][0]["public"]!=restored[1][0]["public"]
                assert edited[1]==repair[1]
                a,b=previous[1],restored[1]
                assert a[1]==b[1] and a[3:]==b[3:]
                expected=receipt[role]["lanes"][crate]
                differences=sum(a[2].get(k)!=b[2].get(k) for k in a[2].keys()|b[2].keys())
                assert differences==expected["changed_public_rows"] and len(a[2])==len(b[2])==expected["total_public_rows"]
                members=verify.native_members(previous[3],restored[3])
                assert members==expected["restored_native_archive"]
                rows=verify.short(obj.executables(prefix+"unchanged-consumer"))
                assert list(map(list,rows))==expected["actual_following_consumer"]
                for phase in ("settled-original","settled-original-again","settled-after","settled-after-again"):
                    floor=sorted(verify.short(obj.executables(prefix+phase)))
                    assert floor==([] if crate=="ruff" else [("ruff_dev","bin",True),("ty_python_semantic","lib",False)])
                for phase in ("invalid","invalid-again"):
                    assert any(r["crate"]=="ruff" for r in obj.executables(prefix+phase,101))
                    assert b"error[E0308]" in obj.read(prefix+phase+"/stderr")
                verdict[role+"/"+crate]={"different_public_definitions":differences,
                    "restored_complete_rmeta":previous[0]["meta_sha"]==restored[0]["meta_sha"],
                    "physical_allocation_counts":[previous[2]["count"],restored[2]["count"]],
                    "equal_full_object_members":members["identical_bodies"],"total_members":members["members"],
                    "actual_following_consumer":rows}
    c=companion.inspect(here/"unicode-and-pointer.zip",False)
    assert c==json.loads((here/"companion-verified.json").read_bytes())
    return verdict

if __name__=="__main__":
    print(json.dumps(reopen(),sort_keys=True,indent=1))
