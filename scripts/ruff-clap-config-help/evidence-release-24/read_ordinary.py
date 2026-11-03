"""Stream actual original objects and independently reopen each normal command and observable verdict."""
import argparse,hashlib,json,os
from pathlib import Path
import shutil,subprocess as sp,tempfile,zipfile
def need(q,msg):
    if not q:raise ValueError(msg)
def hf(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def body(z,key):
    with tempfile.TemporaryFile()as t,z.open(key)as compressed:
        shutil.copyfileobj(compressed,t,1<<18);t.seek(0)
        with sp.Popen(['zstd','-dcq'],stdin=t,stdout=sp.PIPE)as p:
            h=hashlib.sha256();n=0;start=b''
            while chunk:=p.stdout.read(1<<18):
                if not n:start=chunk[:32]
                h.update(chunk);n+=len(chunk)
            need(p.wait()==0,'bad native zstd body')
    return h.hexdigest(),n,start.hex()
def verify(path,expected,mode):
    need(hf(path)==expected,'different complete archive')
    z=zipfile.ZipFile(path);names=z.namelist();need(len(names)==len(set(names)),'duplicate raw paths')
    see=lambda k:json.loads(z.read(k));reg=see('registration.json')
    need(reg['command']==['cargo','+ohm',mode,'-p','ruff','--bin','ruff']and reg['source']==['f3280423f6c535690287e8169c25929f8d6433ce','d136bd8d002a648de5f344df602e492658306f1e'],'different actual command or edit')
    hashes={}
    for key in sorted(k for k in names if k.startswith('bodies/')and k.endswith('.zst')):
        d,n,header=body(z,key)
        need(key=='bodies/'+d+'.zst','different original physical bytes');hashes[d]=[n,header]
    phases=('old','old-unchanged','edit','edited-unchanged','repair','independent-clean-new');prices={};states={}
    for ph in phases:
        hw=see(ph+'/hardware.json');need(hw['instructions']>0 and hw['enabled']==hw['running']>0 and hw['status']==0,(ph,'unqualified hardware'))
        prices[ph]=hw['instructions'];products=see(ph+'/products.json');states[ph]=products
        for k in ('elf','rmeta','embedded_rmeta'):
            if k in products:
                d=products[k]['sha256'];need(hashes[d][0]==products[k]['size'],(ph,k,'different full body'))
        if mode=='build':
            need(hashes[products['elf']['sha256']][1].startswith('7f454c46020101'),'not a Linux native Ruff')
            for label,row in products['verdict']['cases'].items():
                out=z.read(ph+'/'+label+'.stdout');err=z.read(ph+'/'+label+'.stderr')
                need(hashlib.sha256(out).hexdigest()==row['out']and hashlib.sha256(err).hexdigest()==row['err'],(ph,label,'wrong verdict bytes'))
                if label.endswith('help'):need(row['exit']==0 and not err,'unexpected help verdict')
                elif label=='valid-config':need(row['exit']==1 and b'F401'in out and b'os'in out,'invalid valid-config case')
                elif label=='invalid-config':need(row['exit']==2 and b'line-length'in err,'invalid negative config')
            expected_piece=b'--config "'+(b'lint.'if ph.startswith('old') else b'')+b'line-length = 100"'
            matched=[name for name in ('help','check-help','format-help') if expected_piece in b' '.join(z.read(ph+'/'+name+'.stdout').split())];need(sorted(matched)==sorted(products['verdict']['show_example']) and matched,'old/new help not distinguished')
    for bad in ('invalid','invalid-unchanged'):
        raw=z.read(bad+'/stderr');need(b'error[E0308]'in raw and b'ohm_cli_invalid'in raw,'bad program did not fail as registered')
    a=see('admission.json');need(a['strict_product_match']==(states['edit']==states['independent-clean-new']),'wrong cold outcome')
    needed=[]
    if mode=='build':
        for ph in phases:
            if ph.startswith('old'):continue
            needed.append(states[ph]['elf']['sha256'])
        need(all(states[ph]['verdict']==states['edit']['verdict']for ph in phases if not ph.startswith('old')),'different clean behavior')
        need(states['old']['elf']!=states['edit']['elf'],'stale executable')
    return {'cases':prices,'strict_all_products':a['strict_product_match'],'native_edited_empty':len(set(needed))==1 if needed else None,'state_products':{k:{m:r.get('sha256')for m,r in x.items()if isinstance(r,dict)and'sha256'in r}for k,x in states.items()},'program_bodies':hashes}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('file',type=Path);a.add_argument('sha256');a.add_argument('mode',choices=['check','build']);a.add_argument('out',type=Path);args=a.parse_args()
    args.out.write_text(json.dumps(verify(args.file,args.sha256,args.mode),indent=2,sort_keys=True)+'\n')
