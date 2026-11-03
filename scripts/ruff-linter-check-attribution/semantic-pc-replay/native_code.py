"""Reopen the signed driver and the sampled instructions in its hottest unique function."""
from collections import Counter
import gzip
import hashlib
import json
import mmap
from pathlib import Path
import re
import subprocess


def run(z, driver):
    stage=json.loads(z.read("profile/semantic.json"))
    body=json.loads(z.read("pc-sdk.json"))["driver"]
    expected=stage["binaries"][body["path"]]
    with driver.open("rb") as f:
        if hashlib.file_digest(f,"sha256").hexdigest()!=expected["sha256"]:
            raise ValueError("signed driver differs")
    rows=[json.loads(s) for s in gzip.decompress(z.read("profile/leaf-placements.ndjson.gz")).splitlines()]
    chosen=[r for r in rows if r["dso"]==body["path"] and len(r["symbol_ranges"])==1 and "try_mark_previous_green" in r["symbol_ranges"][0][2]]
    (start, size, name),={tuple(r["symbol_ranges"][0]) for r in chosen}
    weight=Counter()
    for r in chosen:
        weight[r["va"]]+=r["samples"]
    dis=subprocess.check_output(["objdump","-d","-w","--start-address="+str(start),"--stop-address="+str(start+size),driver],text=True)
    instructions={}
    for line in dis.splitlines():
        m=re.fullmatch(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.+)",line)
        if m:
            va=int(m[1],16)
            instructions[va]=(bytes.fromhex(m[2]),m[3].strip())
    if not set(weight)<=instructions.keys():
        raise ValueError("sample falls between decoded instructions")
    seg,=[(va,off) for off,va,filesz,_ in expected["segments"] if va<=start and start+size<=va+filesz]
    va,off=seg
    with driver.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as elf:
        body=bytes(elf[start-va+off:start-va+off+size])
    if any(body[ip-start:ip-start+len(inst)]!=inst for ip,(inst,_text) in instructions.items()):
        raise ValueError("objdump disagrees with executable LOAD bytes")
    result=[]
    for ip,hits in weight.most_common():
        inst,text=instructions[ip]
        result.append(dict(va=hex(ip),offset=ip-start,bytes=inst.hex(),op=text,samples=hits))
    return {"function":name, "virtual_address":hex(start),"bytes":size,"function_bytes_sha256":hashlib.sha256(body).hexdigest(),
            "instruction_boundaries":len(instructions),"observed_boundaries":len(weight),"samples":weight.total(),
            "instructions_by_observation_count":result}
