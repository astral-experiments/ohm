"""Keep the worker rebuild for ABI checks and meter only the registered native modules."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tarfile

ARCHIVE = "ba42780456b37115ab3f1f9368a8a8294195650155e8d51e409fa5d731b54ea6"


def check(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sections(data):
    h=struct.unpack_from("<16sHHIQQQIHHHHHH",data)
    check(h[0][:6]==b"\x7fELF\x02\x01" and h[1:3]==(3,62) and h[11]==64,"not a little-endian x86_64 ELF DSO")
    raw=[struct.unpack_from("<IIQQQQIIQQ",data,h[6]+i*h[11]) for i in range(h[12])]
    pool=raw[h[13]]
    strings=data[pool[4]:pool[4]+pool[5]]
    result={}
    for name,kind,flags,address,offset,size,link,info,align,stride in raw[1:]:
        label=strings[name:strings.index(0,name)].decode()
        check(label not in result and (kind==8 or offset+size<=len(data)),("invalid ELF section",label))
        result[label]={"kind":kind,"flags":flags,"address":address,"bytes":size,
                       "sha256":None if kind==8 else digest(data[offset:offset+size])}
    return result


def install(here, output, stats):
    archive=here/"registered-modules.tar.xz"
    registration=json.loads((here/"registered.json").read_bytes())
    check(digest(archive.read_bytes())==registration["archive_sha256"]==ARCHIVE and
          (registration["llvm"],registration["patch"],registration["signed_llvm"])==
          (stats["llvm"],stats["patch"],stats["signed_llvm"]) and
          registration["source_arms"]==stats["source_arms"],"incorrect registered-source inputs")
    infos=registration["modules"]
    check(set(infos)=={a+"-"+m for a in ("stock","strict") for m in ("plain","inspect")},"unrecognized registered pair")
    rebuilt=output/"rebuilt"
    rebuilt.mkdir()
    worker=stats["variants"]
    frozen={n:dict(worker[n]) for n in ("wrapper","loader.so")}
    for n in frozen:
        os.link(output/n,rebuilt/n)
    delta={}
    with tarfile.open(archive,"r:xz") as t:
        names={name+".so" for name in infos}
        check({m.name for m in t.getmembers()}==names and len(t.getmembers())==len(names),"registered archive entries")
        for name,qual in infos.items():
            file=name+".so"
            original=output/file
            original.rename(rebuilt/file)
            member=t.getmember(file)
            check(member.isfile() and 0<member.size<1<<20,"unexpected ELF size")
            data=t.extractfile(member).read()
            check(digest(data)==qual["sha256"] and len(data)==qual["bytes"] and
                  worker[name]["derived_tu"]==qual["derived_tu"],("different source for registered ELF",name))
            original.write_bytes(data)
            original.chmod(0o444)
            a,b=sections(data),sections((rebuilt/file).read_bytes())
            differences={k:[a.get(k),b.get(k)] for k in sorted(a.keys()|b.keys()) if a.get(k)!=b.get(k)}
            runtime=[k for k,(ours,theirs) in differences.items() if k!=".note.gnu.build-id" and
                     any(v and ((v["flags"]&2) or v["kind"] in (4,9)) for v in (ours,theirs))]
            delta[name]={"identical_full_elf":qual["sha256"]==worker[name]["sha256"],
                         "runtime_section_changes":runtime,"all_section_changes":differences}
            frozen[name]=qual
    stats.update(registration=registration,host_variants=worker,registered_vs_host=delta,variants=frozen)
    return rebuilt
