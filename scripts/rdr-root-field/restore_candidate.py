"""Restore the actual candidate against a verified complete original parent, checking all 81 files."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from inputs import C, P, MANIFEST, RUN, JOB, QA, ATTEMPT, build, need, parent
from restore import stream_copy

def restore_candidate(parent_sdk, base, delta_dir, output, qa, run, attempt):
    transfer=json.loads((delta_dir/"manifest.json").read_bytes())
    need((transfer["qa"],str(transfer["run"]),str(transfer["attempt"]))==(qa,str(run),str(attempt)) and
         (transfer["parent_manifest"],transfer["parent_run"],transfer["parent_job"],transfer["parent_qa"],transfer["parent_attempt"])==(MANIFEST,RUN,JOB,QA,ATTEMPT),"wrong native runs")
    need(transfer["roles"]["P"]["commit"]==P and transfer["roles"]["C"]["commit"]==C and set(transfer["files"])==set(base["files"]) and len(transfer["files"])==81,"wrong native sources/members")
    need(build.manifest({Path(n):parent_sdk/n for n in base["files"]})==base["files"],"parent installation differs")
    differences={n:[base["files"][n],row] for n,row in transfer["files"].items() if row!=base["files"][n]}
    need(differences==transfer["differences"] and transfer["driver"] in differences and transfer["same_non_driver"]==81-len(differences),"declared differences")
    tar=delta_dir/"changed-native.tar.zst"
    need([build.sha(tar),tar.stat().st_size]==transfer["delta"],"different compressed native product")
    output.mkdir()
    for n,row in base["files"].items():
        f=output/n;f.parent.mkdir(parents=True,exist_ok=True)
        if n not in differences: shutil.copy2(parent_sdk/n,f)
    seen=set()
    with subprocess.Popen(["zstd","-dq","-c",tar],stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout,mode="r|") as archive:
            for item in archive:
                n=item.name;need(n in differences and item.isfile() and n not in seen,"unregistered native delta member")
                row=transfer["files"][n];need((item.size,item.mode)==(row[1],row[2]),"different tar member flags")
                with archive.extractfile(item) as src:stream_copy(src,output/n,row)
                seen.add(n)
        while proc.stdout.read(1024*1024): pass
        need(proc.wait()==0 and seen==set(differences),"missing/truncated delta")
    need(build.manifest({Path(n):output/n for n in transfer["files"]})==transfer["files"],"finished kit differs")
    need(subprocess.check_output([output/"bin/rustc","-vV"]).decode()==base["compiler_verbose"],"not executable SDK")
    return transfer

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ("original_zips","restored_parent","delta","output"): parser.add_argument(n,type=Path)
    for n in ("qa","run","attempt"):parser.add_argument("--"+n,required=True)
    a=parser.parse_args()
    restore_candidate(a.restored_parent,parent(a.original_zips),a.delta,a.output,a.qa,a.run,a.attempt)
