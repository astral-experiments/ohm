"""Decode the actual Ruff metadata under both typed source-bound compiler schemas."""
import argparse,collections,hashlib,json,pathlib,re,subprocess,sys,zipfile
def read(archive,legacy):
    sys.path.insert(0,str(legacy));import scope_rdr
    h=lambda b:hashlib.sha256(b).hexdigest();src=legacy/'schema/compiler'
    sy=(src/'rustc_span/src/symbol.rs').read_bytes();tb=(src/'rustc_metadata/src/rmeta/mod.rs').read_bytes();assert h(sy)=='b432282257901159c6e2758caa570feb305f01c82b1fa67a19cf6616c6ed1b0d'and h(tb)=='939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c'
    symbols=scope_rdr.decode_symbols(sy.decode());tables=re.findall(r'^    (\w+): Table<',tb.decode().split('define_tables! {',1)[1].split('\n}',1)[0],re.M);assert (len(symbols),len(tables))==(2314,88);result={}
    def compare(a,b):
        ah,at,al,ae,ad=a;bh,bt,bl,be,bd=b;changed_deps=sorted(k for k in ad.keys()|bd.keys()if ad.get(k)!=bd.get(k));changed=[k for k in al.keys()|bl.keys()if al.get(k)!=bl.get(k)]
        return dict(header=[ah,bh],defs=[len(at),len(bt)],identical_defined_identities=at==bt,public_rows=[len(al),len(bl)],changed_public_rows=len(changed),largest_substitutions=collections.Counter((al.get(k),bl.get(k))for k in changed).most_common(3),changed_examples=sorted(at.get(k,bt.get(k))[0]for k in changed)[:12],expansions=[len(ae),len(be)],same_expansions=ae==be,required=[len(ad),len(bd)],changed_required=changed_deps)
    with zipfile.ZipFile(archive)as z:
        reg=json.loads(z.read('registration.json'));case=reg['case']
        for k in ('P','C'):
            v=json.loads(z.read(k+'/factory/sdk.json'))['versions']['rustc'].splitlines()[0]+' (Ohm metadata 3)'
            pairs=[('edit','repair'),('edit','empty-new'),('edit','observed-edit')]+([('cold-old','reverse')]if case=='28392'else [('cold-old','second-cold-old')]);bodies={};phases={}
            for s in sorted({n for pair in pairs for n in pair}):
                rec=json.loads(z.read(k+'/'+s+'/products.json'))['rmeta'];d=rec['sha256'];assert rec['size']<16*2**20
                if d not in bodies:
                    raw=subprocess.check_output(['zstd','-qdc'],input=z.read(k+'/bodies/'+d+'.zst'));assert len(raw)==rec['size']and h(raw)==d;bodies[d]=scope_rdr.decode(raw,symbols,tables,'ruff',v)
                phases[s]=bodies[d]
            result[k]={a+' vs '+b:compare(phases[a],phases[b])for a,b in pairs}
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=pathlib.Path);p.add_argument('sha');p.add_argument('legacy',type=pathlib.Path);p.add_argument('out',type=pathlib.Path);a=p.parse_args();assert hashlib.file_digest(a.archive.open('rb'),'sha256').hexdigest()==a.sha;a.out.write_text(json.dumps(read(a.archive,a.legacy),indent=1,sort_keys=True)+'\n')
