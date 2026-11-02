"""Independent signed-format graph fixture with duplicate stable keys and exact sparse old edges."""
from pathlib import Path
import json,struct,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph,verify_trace
def uleb(x):
    b=bytearray()
    while x>=128:b.append((x&127)|128);x>>=7
    b.append(x);return b
def fp(key):return struct.pack('<QQ',int(key[:16],16),int(key[16:],16))
root='aaaaaaaaaaaaaaaa0102030405060708';leaf='bbbbbbbbbbbbbbbb1112131415161718'
def write(path,rows):
    # Copy only the version string and hash field spelling from a genuine signed file.
    version=b'1.99.0-dev (008a21ac0 2026-10-30)';d=bytearray(b'RSIC\x0a\x00'+bytes([len(version)])+version+b'COMMAND!');counts=[0]*362;edges=0
    for idx,kind,key,value,items in rows:
        head=kind|((len(items)+1)<<11);d+=struct.pack('<HI',head,idx)+fp(key)+fp(value)+bytes(items);counts[kind]+=1;edges+=len(items)
    for n in counts:d+=uleb(n)
    d+=uleb(1)+struct.pack('<QQQ',max(r[0]for r in rows)+1,len(rows),edges)+b'rust-end-file';path.write_bytes(d)
def run(tx):
    tx.mkdir(exist_ok=True)
    old=tx/'previous.bin';new=tx/'current.bin';raw=tx/'trace.log'
    a,b,c='11'*16,'22'*16,'33'*16
    write(old,[(10,5,root,'90'*16,[12,12]),(12,74,leaf,a,[]),(18,74,leaf,b,[])])
    raw.write_text(f'CGUR DRIVER 40000\nCGUR E 1 3 4\nCGUR N 1 fixture\nCGUR W 1 2222222222222222 2222222222222222\nCGUR D 1 1\nCGUR G 1 5 {root[:16]} {root[16:]}\nCGUR T 1\nCGUR C 1 10 4294967295\nCGUR R 1 5c662df already-red 1 10:5:{root} >12:74:{leaf}\nCGUR V 1 4294967295 4294967295\nCGUR X 1 0\nCGUR END 1 0\n')
    target=verify_trace.trace(raw)
    answers=[]
    for current_value,outcome in [(c,'duplicates-conflict'),(b,'duplicates-agree')]:
        write(new,[(9,5,root,'90'*16,[3,5]),(3,74,leaf,b,[]),(5,74,leaf,current_value,[])])
        res=verify_trace.evidence(old,new,None,target);n=res['decisions'][0]['direct_failure']['path'][-1]
        assert n['previous_index']==12 and n['previous_value']==a
        assert n['possible_ordinals_from_parent_0']==[0,1] and 'ordinal_from_parent_0'not in n
        assert n['current_match']==outcome and n['current_candidates']==[dict(index=3,value=b),dict(index=5,value=current_value)]
        assert 'current_index'not in n and n.get('current_value')==(b if outcome=='duplicates-agree'else None);answers.append(n)
    fake=target[1]['R'][0]['nodes'];fake[-1]=(18,74,leaf)
    try:verify_trace.evidence(old,new,None,target)
    except AssertionError:pass
    else:raise AssertionError('accepted a different old index with the same stable key')
    result=dict(cases=answers,rejected_unrelated_prior_index=18);(tx/'result.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':run(Path(sys.argv[1]))
