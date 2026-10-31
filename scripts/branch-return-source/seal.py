"""Create the review-only Git child and its role-specific pack in an external object directory."""
import hashlib
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
F="c6fe8ecda65452c105f85367a009af80cbb5efbc"
H="b676a640c76193a0e241d2517a64e37e156659b9"
O="eb15cd3dc0ab0404f8ad18589569e05a70a4d401"
LIVE="4e7c5b1f765b24ccd585d8ddb7eeae99a02b514e"
def seal(repo):
    common=subprocess.check_output(["git","-C",repo,"rev-parse","--path-format=absolute","--git-common-dir"],text=True).strip()
    with tempfile.TemporaryDirectory() as td:
        store=Path(td)/"objects";store.mkdir()
        env=dict(os.environ,GIT_NO_LAZY_FETCH="1",GIT_TERMINAL_PROMPT="0",GIT_OBJECT_DIRECTORY=str(store),
                 GIT_ALTERNATE_OBJECT_DIRECTORIES=common+"/objects"+(":"+sys.argv[2] if len(sys.argv)>2 else ""),
                 GIT_AUTHOR_NAME="Charlie Marsh",GIT_AUTHOR_EMAIL="charlie.r.marsh@gmail.com",GIT_COMMITTER_NAME="Charlie Marsh",
                 GIT_COMMITTER_EMAIL="charlie.r.marsh@gmail.com",GIT_AUTHOR_DATE="2026-10-31T11:32:00Z",GIT_COMMITTER_DATE="2026-10-31T11:32:00Z")
        def g(*a,data=None):return subprocess.check_output(["git","-C",repo,*a],input=data,env=env)
        def s(*a):return g(*a).decode().strip()
        rows=[]
        for row in g("ls-tree","-z",F).split(b"\0")[:-1]:
            props,name=row.split(b"\t")
            if name in {b"compiler",b"tests"}:
                mode,kind,_=props.split();row=mode+b" "+kind+b" "+s("rev-parse",O+":"+name.decode()).encode()+b"\t"+name
            rows.append(row)
        root=g("mktree","-z","--missing",data=b"\0".join(rows)+b"\0").decode().strip()
        child=g("commit-tree",root,"-p",F,data=b"Apply the exact packed-object follow-up to the reviewed branch-cache source for QA\n").decode().strip()
        print("packed role",child,flush=True)
        ids=set()
        for commit in s("rev-list","--reverse",child,"^"+O,"^"+LIVE).splitlines():
            ids.update([commit,s("rev-parse",commit+"^{tree}")])
            for p in s("diff","--name-only","--no-renames",commit+"^",commit).splitlines():
                for part in [Path(p),*Path(p).parents]:
                    if str(part)==".":continue
                    row=g("ls-tree",commit,"--",str(part)).decode().strip()
                    if row:ids.add(row.split("\t")[0].split()[2])
        print("packing",len(ids),"individual objects",flush=True)
        pack=g("-c","pack.threads=1","pack-objects","--no-reuse-delta","--no-reuse-object","--stdout",
               data=("\n".join(sorted(ids))+"\n").encode())
        if len(pack)>2*2**20:raise ValueError(len(pack))
        dif=g("diff","--no-renames","--binary","--full-index",H,O)
        if dif!=g("diff","--no-renames","--binary","--full-index",F,child):raise ValueError("different product delta")
        live=["AGENTS.md","src/ci/citool/Cargo.lock"]
        if s("diff","--name-only",O,child).splitlines()!=live:raise ValueError("foreign edits")
        rows={k:{"commit":v,"tree":s("rev-parse",v+"^{tree}"),**{n:s("rev-parse",v+":"+n) for n in ("compiler","library","tests")}}
              for k,v in [("F",F),("K",child),("old_full",H),("old_packed",O)]}
        reg={"roles":rows,"pack":{"size":len(pack),"sha256":hashlib.sha256(pack).hexdigest(),"objects":len(ids)},
             "required_live_base":LIVE,"patch_sha256":hashlib.sha256(dif).hexdigest(),"paths":s("diff","--name-only",H,O).splitlines(),
             "live_only":live,"historical_bundle_sha256":"5f12c7fed6e3b36fd151d7d498156fcb73fd6b9d2918c8a534071fce413752a9",
             "traversable_commits":int(s("rev-list","--count",child,"^"+O))}
        (HERE/"original-full-index.patch.gz").write_bytes(gzip.compress(dif,compresslevel=9,mtime=0))
        (HERE/"role-history.pack").write_bytes(pack)
        (HERE/"roles.json").write_text(json.dumps(reg,sort_keys=True,indent=2)+"\n")
        print(json.dumps(reg),flush=True)
if __name__=="__main__":seal(Path(sys.argv[1]).resolve())
