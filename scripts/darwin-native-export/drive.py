"""Bind native Cargo, the distributed compiler and the independently rebuilt compiler."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
W=Path(os.environ["GITHUB_WORKSPACE"]).resolve()
HOST="aarch64-apple-darwin"
PARENT="556a8364f1485a03be31b1a50c250d63198a943d"
CANDIDATE="00526133a6352eb88eca70382000e6221253235c"
CARGO="32156236e76773728b3e7655d64d32ea8c3023b165f25a2754c7e5c50669f366"
sys.path.insert(0,str(W/"native-reader/scripts/rc22-complete-smoke"))
import media
import installed
import focused

def original(root):
    for folder in ("media","receipts","reports"):
        (root/folder).mkdir(parents=True)
    (root/"receipts/installer").mkdir()
    cfg=media.CFG
    g=media.fetch(root,cfg["global"],"Retain global release assets")
    p=media.fetch(root,cfg["targets"][HOST]["platform"],"Retain distribution artifacts")
    media.release(root,HOST,g,p)
    installed.catalog(root,HOST)
    _,sdk,_=focused.installation(root,HOST,"original",root/"receipts/installer")
    kit=media.fetch(root,cfg["targets"][HOST]["native"],"Publish reusable native SDK")
    media.fixed(root,HOST,kit)
    assert media.sha(root/"fourfix-cargo")==CARGO
    # Change only Cargo in this private installation, after inspecting the shipped SDK.
    (sdk/"bin/cargo").unlink()
    shutil.copy2(root/"fourfix-cargo",sdk/"bin/cargo")
    media.save(root/"receipts/installed-cargo.json",installed.inspect(root,HOST,sdk,"fourfix"))
    (root/"parent").symlink_to(sdk,target_is_directory=True)

def candidate(root):
    sys.path.insert(0,str(W/"transport/scripts/rc22-native"))
    import sdk
    rust=root/"rust"
    spec=json.loads((root/"reports/qualified-source.json").read_bytes())
    assert spec["candidate"]==CANDIDATE and spec["trees"]["compiler"]=="56204f7d037d7dfcac798c33568b544c7e5cbe18"
    assert subprocess.check_output(["git","-C",rust,"rev-parse","HEAD"]).decode().strip()==CANDIDATE
    cmd=["./x","--ci","false","--set","build.submodules=false","--set","rust.channel=dev","--set","rust.omit-git-hash=false","--set","rust.debug-assertions=false","--set","rust.lto=off","--set","llvm.download-ci-llvm=true","build","--stage","1","-j4","--host",HOST,"--target",HOST,"compiler/rustc","library","src/tools/rustdoc"]
    sdk.log_run(cmd,rust,root/"reports/bootstrap.log")
    assert not subprocess.check_output(["git","-C",rust,"status","--porcelain","--untracked-files=no"])
    dst=root/"candidate"
    sdk.freeze(rust/"build"/HOST/"stage1",dst,rust,HOST)
    shutil.copy2(root/"fourfix-cargo",dst/"bin/cargo")
    linker=Path(subprocess.check_output(["/usr/bin/xcrun","-f","ld"],text=True).strip()).resolve(strict=True)
    media.save(root/"receipts/candidate-sdk.json",{"source":spec,"argv":cmd,"log":media.sha(root/"reports/bootstrap.log"),
               "cargo":media.sha(dst/"bin/cargo"),"rustc":media.sha(dst/"bin/rustc"),"xcode_linker":media.sha(linker),"xcode":subprocess.check_output(["xcodebuild","-version"],text=True)})

def exercise(root,role):
    sys.path.insert(0,str(W/"transport/scripts/rc22-native"))
    import common
    private=root/("context-"+role)
    private.mkdir()
    e=common.context(private,root/role)
    assert media.sha(root/role/"bin/cargo")==CARGO
    for mode in ("build","test"):
        subprocess.run([sys.executable,"-IB",HERE/"probe.py",root/(role+"-"+mode),root/"receipts"/role/mode,e["RUSTUP_HOME"],
                        private/"proxies",mode,role,PARENT if role=="parent" else CANDIDATE,CARGO],check=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("op",choices=("original","candidate","probe-parent","probe-candidate"))
    p.add_argument("work",type=Path)
    a=p.parse_args()
    assert (platform.system(),platform.machine())==("Darwin","arm64")
    root=a.work.resolve()
    if a.op.startswith("probe-"):
        exercise(root,a.op.removeprefix("probe-"))
    else:
        {"original":original,"candidate":candidate}[a.op](root)
