"""Admit a complete Ruff archive only across the actual typed temporary filename fields."""
import gzip
import json
import re

import archive_diagnostic as a

PAT=re.compile(rb"ruff_workspace-6f5918319b095248\.([a-z0-9]{25})\.([a-z0-9]{7})\.rcgu\.o")
MASK=b"0000000"


def project(data, expected):
    layout=a.ar_layout(memoryview(data))
    all_rows=layout["ordered_members"]
    a.need([u['name']for u in all_rows[:4]]==['/','//','lib.rmeta','lib.rmeta-link'] and len(all_rows)==129, "Ruff archive schema")
    longnames,link=all_rows[1],all_rows[3]
    [section]=[s for s in link["elf_sections"]if s["name"]==".rmeta-link"]
    start=link["body_offset"]+section["offset"];stop=start+section["bytes"]
    count=data[start]; a.need(count==125 and count==len(expected),"canonical one-byte object count")
    pos=start+1; g=longnames["body_offset"]; names_at=g; slots=[]; cgu_ids=[]; suffix=None
    for u in all_rows[4:]:
        name=u["name"].encode("ascii"); parsed=PAT.fullmatch(name)
        a.need(parsed is not None,"unknown archive member name")
        key=parsed[1].decode("ascii");stamp=parsed[2]
        a.need(expected.get(key)==u["payload_sha256"] and key not in cgu_ids,"unknown, duplicate or changed ordinary object")
        a.need(int(stamp,36)<=0xffffffff and (suffix is None or suffix==stamp),"more than one valid random u32 per image")
        suffix=stamp;cgu_ids.append(key)
        rel=bytes.fromhex(u["raw_header_hex"])[:16].rstrip()
        a.need(rel==b"/"+str(names_at-g).encode() and data[names_at:names_at+len(name)+2]==name+b"/\n","ordered ar filename and offset")
        a.need(len(name)<128 and data[pos]==len(name) and data[pos+1:pos+1+len(name)]==name and data[pos+1+len(name)]==193,
               "typed rmeta-link string must exactly match the ar filename")
        slots.append((names_at+parsed.start(2),"ar",key));slots.append((pos+1+parsed.start(2),"rmeta-link",key))
        names_at+=len(name)+2;pos+=len(name)+2
    a.need(names_at==g+longnames["body_bytes"] and data[pos:stop]==b"\0rust-end-file" and set(cgu_ids)==set(expected),
           "unexpected string-table bytes, native libraries, metadata footer, or missing CGU")
    ordered=sorted(t for t,_,_ in slots)
    a.need(len(ordered)==250 and all(b-a>=7 for a,b in zip(ordered,ordered[1:])),"overlapping or missing slots")
    restored=bytearray(data)
    for t,_,_ in slots:
        a.need(data[t:t+len(suffix)]==suffix,"wrong slot bytes")
        restored[t:t+len(suffix)]=MASK
    return restored,{"suffix":suffix.decode(),"u32":int(suffix,36),"order":cgu_ids,
                     "slots":[(n,c,k)for n,c,k in sorted(slots)],"raw_index":all_rows[0]["payload_sha256"],
                     "full_main_rmeta":all_rows[2]["payload_sha256"],"projected_sha256":a.H(restored),
                     "indices":all_rows[0]["gnu_index"],"physical_names":{r["name"]:r['body_offset'] for r in all_rows}}



def match(out, expected):
    reference = None
    arms = {}
    for arm in a.ARMS:
        saved = json.loads((out / f"archive-{arm}.json").read_bytes())
        packed = out / f"archive-{arm}.rlib.gz"
        a.need(0 < saved["bytes"] <= 512 << 20 and a.H(packed.read_bytes()) == saved["gzip_sha256"],
               "changed or oversized saved archive")
        with gzip.open(packed, "rb") as stream:
            original = stream.read(saved["bytes"] + 1)
        a.need(len(original) == saved["bytes"] and a.H(original) == saved["sha256"], "different full saved archive")
        projected, facts = project(original, expected)
        if reference is None:
            reference = projected
        else:
            a.need(reference == projected, "ordinary and observed archives differ beyond the typed temporary names")
        arms[arm] = {"original": saved["sha256"], "suffix": facts["suffix"], "canonical": facts["projected_sha256"],
                     "fields": len(facts["slots"]), "index": facts["raw_index"], "main_metadata": facts["full_main_rmeta"]}
    a.need(len(arms) == 3, "required original, ordinary repeat and observed histories")
    a.save(out / "typed-archive-admission.json", arms)
    return a.H(reference)
