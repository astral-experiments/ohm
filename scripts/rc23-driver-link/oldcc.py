"""Extract the real 4.8.5 compiler from four signed Ubuntu records for post-distribution qualification."""
from pathlib import Path
import lzma
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g

def prepare(work,cache=None):
    auth=g.read(g.HERE/"old-cc.json")
    work.mkdir();media=work/"media";media.mkdir();root=work/"root";root.mkdir()
    def asset(name,url,digest,size):
        p=media/name
        if cache is not None:
            clean=cache/name
            assert clean.is_file() and not clean.is_symlink()
            shutil.copyfile(clean,p)
        else:
            subprocess.run(["curl","--proto","=https","--proto-redir","=https","--tlsv1.2","--fail","--location","--silent","--show-error","--retry","2","--max-filesize",str(size),"--output",p,auth["archive_root"]+url],check=True)
        assert p.stat().st_size==size and g.sha(p)==digest
        return p
    signed=asset("bionic.InRelease","dists/bionic/InRelease",auth["signed_index"],auth["release_bytes"])
    sig=subprocess.run(["gpgv","--status-fd=1","--keyring","/usr/share/keyrings/ubuntu-archive-keyring.gpg",signed],capture_output=True,text=True,check=True)
    valid=[s.split()[2] for s in sig.stdout.splitlines() if s.startswith("[GNUPG:] VALIDSIG ")]
    assert valid==[auth["archive_signer"]]
    key,size,name=auth["package_index"]
    signed_sha=signed.read_text().split("\nSHA256:\n",1)[1].split("\nSHA512:\n",1)[0]
    assert [s.split() for s in signed_sha.splitlines() if s.endswith(" "+name)]==[[key,size,name]]
    idx=asset("bionic-universe.xz","dists/bionic/"+name,key,int(size))
    actual={}
    with lzma.open(idx,"rt") as f:
        item={}
        for s in f:
            if s=="\n":
                k=item.get("Package")
                if k in auth["packages"]:
                    assert k not in actual;actual[k]={n:item[n] for n in auth["packages"][k]}
                item={}
            elif not s.startswith(" ") and ": " in s:
                k,v=s.split(": ",1);item[k]=v.strip()
    assert actual==auth["packages"] and len(actual)==4
    for k,v in sorted(actual.items()):
        assert v["Version"]=="4.8.5-4ubuntu8" and v["Filename"].startswith("pool/universe/g/gcc-4.8/")
        p=asset(Path(v["Filename"]).name,v["Filename"],v["SHA256"],int(v["Size"]))
        subprocess.run(["dpkg-deb","-x",p,root],check=True)
    gcc=root/"usr/bin/gcc-4.8";collect=root/"usr/lib/gcc/x86_64-linux-gnu/4.8/collect2"
    assert g.sha(gcc)==auth["gcc_sha256"] and g.sha(collect)==auth["collect2_sha256"]
    banner=subprocess.check_output([gcc,"-dumpversion"],text=True).strip();assert banner=="4.8"
    return {"authority_sha256":g.sha(g.HERE/"old-cc.json"),"archive_signer":valid[0],"signed_release_sha256":g.sha(signed),"index_sha256":g.sha(idx),
            "packages":actual,"gcc":str(gcc),"gcc_sha256":g.sha(gcc),"collect2_sha256":g.sha(collect),"gcc_dumpversion":banner}
if __name__=="__main__":
    w=g.checkout("build")
    result=prepare(w/"driver-oldcc")
    g.save(w/"trait-evidence/old-cc-inputs.json",result)
