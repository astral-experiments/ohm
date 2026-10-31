"""Decode the signed original bounded root headers; compare available roots to full rmeta too."""
import gzip, hashlib, json, struct, sys, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import decode as x
FIRST='eii deps dylib lib_features stability_implications lang_items lang_items_missing stripped_cfg diagnostic canonical native_libraries foreign_modules traits'.split()
SECOND='debugger_visualizers exportable_items stable_order_of_exportable_impls exported_non_generic_symbols exported_generic_symbols'.split()
def header(window,offset):
    r=x.D(window,0);r.root=offset
    x.need(r.unsigned()==0 and r.string()=='x86_64-unknown-linux-gnu','GNU target')
    hashes=r.take(32).hex();owner=r.symbol();x.need(r.flag()==r.flag()==0,'rust library')
    name=r.string();stable=r.take(8).hex()
    if r.flag():x.need(r.unsigned() in range(3),'panic')
    x.need(r.unsigned() in range(3) and r.unsigned() in range(5),'panic/edition')
    for _ in range(4):r.flag()
    fields={}
    def array(label):
        at=r.pos;n,target=r.array()
        fields[label]={'count':n,'position':target,'encoded_offset':offset+at,'encoded':window[at:r.pos].hex()}
    for label in FIRST:array(label)
    x.need(r.unsigned() in (0,1),'impl kind')
    for label in ('impls','incoherent_impls','interpret_alloc_index'):array(label)
    x.need(not r.flag(),'nonstandard procedural macro data')
    for label in SECOND:array(label)
    c_linker=r.flag()
    return {'name':owner,'extra_filename':name,'stable':stable,'private_public':hashes,'root_prefix_used':r.pos,'fields':fields,'has_generic_symbols_for_c_linker':c_linker}
def main():
    with x.ZIP.open('rb') as f:x.need(hashlib.file_digest(f,'sha256').hexdigest()==x.EXPECTED,'zip pin')
    with zipfile.ZipFile(x.ZIP) as z:
        reg=json.loads(z.read('registration.json'))
        x.need((reg['run'],reg['attempt'],reg['head'])==(41189297097,1,'42ab30fd5e6bcdcf908df81de9baac65ca64fbf9'),'run')
        def cas(key):
            b=gzip.decompress(z.read('metadata-cas/'+key+'.gz'));x.need(x.sha(b)==key,'CAS');return b
        output={}
        for phase in ('prior-repeat','edited','edit-repeat','restored','restore-repeat'):
            hh=json.loads(gzip.decompress(z.read('T/'+phase+'/workspace-headers.json.gz')))
            pp=json.loads(gzip.decompress(z.read('T/'+phase+'/work-products.json.gz')))
            out={};names=set(pp)|{'ruff_notebook','ty_python_core','ty_python_semantic'}
            for name in sorted(names):
                candidates=[(k,h) for k,h in hh.items() if h['target']==name and h['size']]
                vals=set((w['sha256'],w['header_sha256'],w['root_sha256']) for k,w in candidates)
                x.need(len(vals)==1,'distinct named producers')
                k,w=candidates[0];initial,root=cas(w['header_sha256']),cas(w['root_sha256'])
                x.need(initial[:8]==b'rust\x00\x00\x00\x0a' and struct.unpack_from('<Q',initial,8)[0]==w['root_offset'] and len(initial)==w['header_bytes'],'metadata header')
                s=x.Cursor(initial,16);u=s.unsigned();stamp=s.take(u).decode();x.need(stamp==w['issuer'] and '(Ohm metadata 1)' in stamp and 'c79998a5c' in stamp and s.pos==len(initial),'issuer')
                x.need(len(root)==w['root_bytes']==min(384,w['size']-w['root_offset']),'truncation')
                v=header(root,w['root_offset']);x.need(v['name']==('str',name),'root issuer')
                if name in pp:
                    full=cas(pp[name]['meta']['cargo']['sha256']);x.need(x.sha(full)==w['sha256'] and full[w['root_offset']:w['root_offset']+len(root)]==root,'complete root disagrees')
                out[name]=dict(archive_paths=[k for k,w in candidates],metadata_sha256=w['sha256'],metadata_size=w['size'],root_offset=w['root_offset'],header_sha256=w['header_sha256'],root_sha256=w['root_sha256'],decoded=v)
            output[phase]=out
        for n in names-{'ty_python_semantic'}:
            x.need(output['prior-repeat'][n]['metadata_sha256']==output['restored'][n]['metadata_sha256']==output['restore-repeat'][n]['metadata_sha256'] and output['edited'][n]['metadata_sha256']==output['edit-repeat'][n]['metadata_sha256'],'repair')
        # Input registration authenticates byte-exact repeats. The original full heavy semantic's
        # SHA after the reverse+restore differs from initial, although the typed roster count agrees.
        h='ty_python_semantic'
        x.need(output['prior-repeat'][h]['metadata_sha256']!=output['restored'][h]['metadata_sha256'] and output['restored'][h]['metadata_sha256']==output['restore-repeat'][h]['metadata_sha256'] and output['edited'][h]['metadata_sha256']==output['edit-repeat'][h]['metadata_sha256'],'known distinct restored heavy semantic')
        for p,expect in [('prior-repeat',808),('edited',807),('edit-repeat',807),('restored',808),('restore-repeat',808)]:
            x.need(output[p]['ruff_notebook']['decoded']['fields']['exported_generic_symbols']['count']==expect and output[p]['ruff_notebook']['decoded']['fields']['exported_non_generic_symbols']['count']==60,'actual export controls')
        b=(json.dumps({'zip_sha256':x.EXPECTED,'compiler':x.PIN,'partial_headers':output},sort_keys=True,separators=(',',':'))+'\n').encode()
        (x.BASE/'headers.json.gz').write_bytes(gzip.compress(b,mtime=0));print(x.sha(b),x.sha((x.BASE/'headers.json.gz').read_bytes()))
        for ph in output:
            r=output[ph]['ruff_notebook'];print(ph,r['root_offset'],r['root_sha256'],r['decoded']['fields']['exported_generic_symbols'])
if __name__=='__main__':main()
