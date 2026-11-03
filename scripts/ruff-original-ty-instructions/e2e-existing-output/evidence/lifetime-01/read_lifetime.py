"""Reopen one authenticated original archive. The executable count and byte hashes come from the actual observation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

RAW='7b4b0e8d8402eab3902b744f05ad6c5c4195146302fe9f1ba8f1e96b9c9ac49b'
OLD='f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2'
NEW='86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563'
def sha(data):return hashlib.sha256(data).hexdigest()
def reopen(path):
    assert path.stat().st_size==6136928 and sha(path.read_bytes())==RAW
    with ZipFile(path) as z:
        reg=json.loads(z.read('registration.json'));assert reg['run']=='41701252791' and reg['head']=='6f0798bccc16f42339cb3ea1e3287450e2298420'
        names=z.namelist();assert len(names)==len(set(names)) and not any('.elf' in n for n in names)
        def inventory(p):return json.loads(gzip.decompress(z.read(p+'/inventory.json.gz')))
        result={};args={}
        for p,prior in [('ordinary-edit',OLD),('ordinary-unchanged',NEW)]:
            phys=json.loads(z.read(p+'/output-lifetime.json'));assert phys==json.loads(z.read('lifetime.json'))[p]
            before=phys['before'];after=phys['after'];canonical=phys['canonical'];assert before['dev']==after['dev'] and before['ino']!=after['ino'] and before['links']==after['links']==1
            assert before['sha256']==prior and after['sha256']==NEW
            emitted=inventory(p);assert len(emitted['executables'])==102 and canonical.endswith('/'+emitted['binary'])
            receipts=[];images=[];execution=z.read(p+'/tasks/epochs.tsv').splitlines()
            for file in sorted((n for n in names if n.startswith(p+'/tasks/canonical-')),key=lambda x:int(x.rsplit('-',1)[1][:-4])):
                fields=z.read(file).decode().rstrip('\n').split('\t');number,pid,exe,state,stable,dev,ino,nlink,size,mode,full,path=fields
                assert (path,state,stable,int(dev),int(ino),int(nlink),int(size),mode,full)==(canonical,'present','1',before['dev'],before['ino'],1,before['bytes'],'100755',prior)
                packet=z.read(p+'/tasks/'+number.zfill(5)+'.nul').split(b'\0');assert packet[-1]==b'' and packet[0]==pid.encode() and packet[3]==exe.encode()
                argv=packet[4:-1];assert [bytes(x).decode()for x in execution if x.startswith(f'I {number} '.encode()) and x.endswith(b' exec')]
                image=Path(exe).name;images.append(image)
                if image=='ld.bfd':
                    assert len(argv)==446 and argv[argv.index(b'-o')+1].decode()==canonical
                    args[p]=argv
                receipts.append({'epoch':int(number),'pid':int(pid),'image':image,'argv_sha256':sha(b'\0'.join(argv)+b'\0')})
            assert images==['rustc','x86_64-linux-gnu-gcc-13','collect2','ld.bfd']
            result[p]={'before':before,'after':after,'canonical':canonical,'epochs':receipts,'executables':102}
        assert len(inventory('ordinary-old')['executables'])==102
        rosters=set()
        for tag,success in [('old-verdict',True),('old-on-new-verdict',False),('ordinary-edit-verdict',True),('ordinary-unchanged-verdict',True)]:
            listing=z.read(tag+'/test-list');lines=listing.splitlines();assert len([l for l in lines if l.endswith(b': test')])==200
            rosters.add(sha(listing));stdout=z.read(tag+'/stdout')
            expected=b'test commands::debug_command ... '+(b'ok'if success else b'FAILED')
            assert expected in stdout
        assert len(rosters)==1
        a,b=args.values();changed={i:[x.decode(),y.decode()]for i,(x,y)in enumerate(zip(a,b))if x!=y};assert set(changed)=={4,23,36}
        for v in changed[4]:assert re.fullmatch(r'-plugin-opt=-fresolution=/tmp/cc[0-9A-Za-z]+\.res',v)
        for v in changed[23]:assert v.startswith('-L') and v.endswith('/raw-dylibs')
        for v in changed[36]:assert Path(v).name=='symbols.o'
        return {'registration':reg,'original_sha256':RAW,'stages':result,'test_roster_sha256':rosters.pop(),'changed_argv':changed}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('original',type=Path);print(json.dumps(reopen(ap.parse_args().original),indent=2,sort_keys=True))
