"""Reconstruct and verify only the three source directories rooted in the actual matched parent commit."""
import hashlib,os,subprocess
from pathlib import Path

def materialize(root,pack,plan):
    expected=plan['support_pack'];assert (len(pack),hashlib.sha256(pack).hexdigest())==(expected['bytes'],expected['sha256']);assert pack[:4]==b'PACK'and int.from_bytes(pack[8:12],'big')==expected['objects'];root.mkdir();g=lambda *a:subprocess.check_output(['git','-C',root,*a]);g('init','--quiet','--object-format=sha1');subprocess.run(['git','-C',root,'index-pack','--stdin'],input=pack,check=True,stdout=subprocess.PIPE);head=plan['founder_parent'];assert g('cat-file','-t',head).strip()==b'commit';g('update-ref','refs/heads/frozen',head);g('symbolic-ref','HEAD','refs/heads/frozen');total=0
    for directory,tree in plan['support_trees'].items():
        assert g('rev-parse','HEAD:'+directory).strip().decode()==tree
        for line in g('ls-tree','-r','-z',tree).split(b'\0')[:-1]:
            meta,n=line.split(b'\t',1);mode,kind,oid=meta.split();assert kind==b'blob'and mode in(b'100644',b'100755');relative=Path(n.decode());assert not relative.is_absolute()and all(x not in ('.','..','.git')for x in relative.parts);body=g('cat-file','blob',oid.decode());assert len(body)<2<<20 and hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==oid.decode();dest=root/directory/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body);os.chmod(dest,int(mode,8)&0o777);total+=1
    assert total==expected['regular_source_files'];return root
