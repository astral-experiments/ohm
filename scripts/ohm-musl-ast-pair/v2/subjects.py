"""Use a new SDK view. Swaps preserve each enrolled regular file's inode and timestamps."""
import os
from pathlib import Path
import re
import shutil
import subprocess
from evidence import fid, save, sha, TARGET

SOURCE={"P":"adea62b64bb86ad18946457dfb59f36b2d8fcab4",
        "C":"d52336754e01c65758f0be7335b191be47baf02f",
        "signed":"2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c",
        "strict":"761ea115605c34f11a1cd29afd68812c1e1359dd",
        "aware":"c18e91b514b2c4e4966c9ab03232c804af3e1b57"}

CARGO_SHA={"signed":"4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e",
           "strict":"035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4",
           "aware":"9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826"}

class Subjects:
    def __init__(self, spec, root, out, readers):
        self.spec,self.out,self.active=spec,out,None
        self.source=Path(spec["sdk"]).resolve(strict=True)
        self.sdk=root/"rustup/toolchains/ohm"; self.sdk.mkdir(parents=True)
        self.driver=spec["driver_basename"]
        assert re.fullmatch(r"librustc_driver-[0-9a-f]+\.so",self.driver)
        self.roles={k:spec["drivers"][k] for k in ("P","C")}
        self.roles.update({k:spec["cargos"][k] for k in readers})
        ids={}
        for name,row in self.roles.items():
            p=Path(row["path"]).resolve(strict=True)
            assert p.stat().st_dev==self.sdk.stat().st_dev,("use same-filesystem private scratch",p)
            assert row["source"]==SOURCE[name] and sha(p)==row["sha256"]
            if name in CARGO_SHA:assert row["sha256"]==CARGO_SHA[name],(name,row)
            ids[name]={"physical":str(p),"identity":fid(p),**row}
        assert len({v["sha256"] for v in self.roles.values()})==len(self.roles)
        assert sha(self.source/"bin/rustc")==spec["frontend_sha256"]
        for top in self.source.iterdir():
            d=self.sdk/top.name
            if top.name not in {"bin","lib"}:
                d.symlink_to(top); continue
            d.mkdir()
            for child in top.iterdir():
                if child.name=="cargo" and top.name=="bin" or child.name==self.driver and top.name=="lib":
                    continue
                target=d/child.name
                if top.name=="bin" and child.name in {"rustc","rustdoc"}:
                    os.link(child.resolve(strict=True),target)
                else:target.symlink_to(child)
        self.shims=root/"proxies";self.shims.mkdir()
        rustup=Path(shutil.which("rustup")).resolve(strict=True)
        for n in ("rustup","cargo","rustc","rustdoc"):(self.shims/n).symlink_to(rustup)
        self.env={"HOME":str(root/"home"),"CARGO_HOME":str(root/"cargo-home"),
                  "RUSTUP_HOME":str(root/"rustup"),"PATH":str(self.shims)+":/usr/local/bin:/usr/bin:/bin",
                  "RUSTUP_AUTO_INSTALL":"0","CARGO_NET_OFFLINE":"true","CARGO_TERM_COLOR":"never",
                  "CARGO_CACHE_AUTO_CLEAN_FREQUENCY":"never","LANG":"C","LC_ALL":"C","TZ":"UTC",
                  "GIT_CONFIG_GLOBAL":os.devnull,"GIT_CONFIG_NOSYSTEM":"1"}
        for k in ("HOME","CARGO_HOME"):Path(self.env[k]).mkdir()
        self.version=None;self.visits=[]
        libs=self.sdk/"lib/rustlib"/TARGET/"lib"
        assert list(libs.glob("libstd-*.rlib")) and (libs/"self-contained/libc.a").is_file()
        target={str(p.relative_to(self.sdk)):[fid(p),sha(p)] for p in libs.rglob("*") if p.is_file()}
        save(out/"subjects.json",{"sources":ids,"frontend":[spec["frontend_sha256"],fid(self.sdk/"bin/rustc")],
                                   "sdk_base":str(self.source),"target_members":target})
    def select(self,driver,reader):
        if self.active==(driver,reader):return
        for role,dest in ((driver,self.sdk/"lib"/self.driver),(reader,self.sdk/"bin/cargo")):
            original=Path(self.roles[role]["path"]).resolve(strict=True)
            if not dest.exists() or not dest.samefile(original):
                pending=dest.with_name(dest.name+".new")
                os.link(original,pending)
                pending.replace(dest)
            assert fid(dest)==fid(original) and sha(dest)==self.roles[role]["sha256"]
        def query(args):return subprocess.check_output(args,env=self.env,text=True).strip()
        for n in ("rustc","cargo"):
            assert Path(query(["rustup","which","--toolchain","ohm",n])).samefile(self.sdk/"bin"/n)
        assert Path(query(["rustc","+ohm","--print","sysroot"])).samefile(self.sdk)
        vv=query(["rustc","+ohm","-vV"]);cv=query(["cargo","+ohm","-Vv"])
        assert "commit-hash: "+SOURCE[reader] in cv,cv
        if self.version is None:self.version=vv
        assert vv==self.version, ("requires the complete same rustc -vV stamp",vv,self.version)
        self.active=driver,reader
        self.visits.append({"driver":driver,"reader":reader,"driver_id":fid(self.sdk/"lib"/self.driver),
                            "cargo_id":fid(self.sdk/"bin/cargo"),"rustc":vv,"cargo":cv})
        save(self.out/f"selection-{len(self.visits):02d}.json",self.visits[-1])
