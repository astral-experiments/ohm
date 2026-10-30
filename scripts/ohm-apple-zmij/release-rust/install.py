"""Import the exact published #281 ancestry after the independently qualified versioned source prep."""
from pathlib import Path
import hashlib,json,subprocess,sys
here=Path(__file__).resolve().parent
src=Path(sys.argv[1]).resolve()
s=json.loads((here/"source.json").read_bytes())
def git(*a,data=None):return subprocess.check_output(["git","-C",str(src),*a],input=data)
def text(*a):return git(*a).decode().strip()
prior="d97de79d0462fec6b08474c677857b6b058f56c2";assert text("rev-parse","HEAD")==prior
pack=(here/"source.pack").read_bytes();assert len(pack)==s["bytes"] and hashlib.sha256(pack).hexdigest()==s["sha256"]
assert int.from_bytes(pack[8:12],"big")==s["objects"]==81
git("index-pack","--stdin",data=pack)
head=s["child"]
for c,v in s["vertices"].items():
 for a,h in v.items():assert text("rev-parse",c+a)==h
assert text("rev-list","--count",head,"--not",s["base"])=="9"
assert text("diff","--no-renames","--name-only",prior,head)==".github/workflows/ci.yml"
assert git("ls-tree",head,"compiler","library","tests","src")==git("ls-tree",prior,"compiler","library","tests","src")
git("update-ref","refs/heads/qa-published-apple-281",head)
git("checkout","--quiet","--detach",head)
assert text("rev-parse","HEAD^{tree}")=="2416f886c016ea28bb1b9d2ac341f2c131de88d5" and not text("status","--porcelain","--untracked-files=no")
print(json.dumps(s,sort_keys=True))
