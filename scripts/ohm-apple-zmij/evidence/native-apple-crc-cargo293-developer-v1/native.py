"""Reopen ordinary Cargo, kernel execs, native products and independent references from the hosted ZIP."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from macho import archive_objects, section, sha

P="444c0273a2e2bc0b161e988d43c882349bc2d7a6";C="82911b516fb35608fd70ada4deb6f8429277f410"
S="2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c";R="735e1528ed741015c57676dccf05dbdc0ff7bed1"
TREE="9cb7035b7adc52ecac48495666b95ba857ed3cdd";PACK="775494565d10143c9f34679ad21d90020ed9c82518f774fde923f4d5ef90ea4b"
SIGNED="7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
LD={"ld","ld-classic","ld-prime","ld64","ld.lld","rust-lld","wild-ld","ld64.lld"}
L=PurePosixPath
def compact(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def pretty(x):return (json.dumps(x,sort_keys=True,indent=2)+'\n').encode()
def assertat(cond,where):
    if not cond:raise ValueError(str(where))
def digestfile(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,b):
    if p.exists():assert p.read_bytes()==b,p
    else:p.write_bytes(b)

class Dataset:
    def __init__(self,z):
        self.z=z;self.names={a.filename for a in z.infolist() if not a.is_dir()};self.images={};self.lds=set()
        assert len(self.names)==len([a for a in z.infolist() if not a.is_dir()])
        self.prefix='' if 'provider-matrix/registration.json' in self.names else 'receipts/'
        self.complete=self.prefix+'release.json' in self.names
        from objects import Images
        self.image_proofs=Images(self)
    def raw(self,n):return self.z.read(self.prefix+n)
    def js(self,n):return json.loads(self.raw(n))
    def gz(self,n):return gzip.decompress(self.raw(n))
    def exists(self,n):return self.prefix+n in self.names
    def providers(self):
        d=self.js('provider-matrix/providers.json');ret={}
        for v in [17,29]:
            base='provider-matrix/provider-'+str(v)
            a=self.raw(base+'.a');o=self.raw(base+'.o')
            (name,body),=archive_objects(a);kind,code,_=section(o)
            assert name.rstrip(b'/')==b'provider.o' and body.startswith(o) and not body[len(o):].strip(b'\x00\n')
            assert kind==1 and code==struct.pack('<II',0x52800000 | (v<<5),0xd65f03c0)
            assert sha(o)==d[str(v)]['object'] and sha(a)==d[str(v)]['archive']
            assert all(t['exit']==0 for t in d[str(v)]['calls'])
            ret[str(v)]={'object':sha(o),'archive':sha(a),'object_text':code.hex(),'archive_bytes':len(a)}
        return ret
    def product(self,kind,key):
        if (kind,key) not in self.images:
            b=self.gz(kind+'/'+key+'.macho.gz');k,t,u=section(b)
            assert sha(b)==key and k==2 and len(u)==1
            if kind=='edge-images':assert any(word&0xffe0fc00==0x1ac04800 for (word,) in struct.iter_unpack('<I',t)), 'no CRC32W in running executable'
            self.images[kind,key]={'raw':key,'text':[len(t),sha(t)],'uuid':u[0],'bytes':len(b)}
        return self.images[kind,key]
    def actual(self,p,where,proof):
        out=self.gz(p+'/stdout.gz');err=self.gz(p+'/stderr.gz');raw=self.gz(p+'/exec.json.gz')
        digests={'stdout':sha(out),'stderr':sha(err),'native_events':sha(raw)}
        assertat(proof['streams']==digests,(p,'raw'))
        cargo=list(map(json.loads,out.splitlines()));x=json.loads(raw)
        assert cargo[-1]=={'reason':'build-finished','success':proof['status']==0}
        arts=[a for a in cargo if a['reason']=='compiler-artifact']
        unit=lambda a:[a['package_id'],a['target']['name'],','.join(a['target']['kind']),a['features'],compact(a['profile'])]
        keys=sorted(unit(a) for a in arts)
        assertat(keys==proof.get('typed',proof.get('roster')) and len(keys)==len(set(map(compact,keys))),(p,'complete typed roster'))
        assertat(sorted(unit(a) for a in arts if not a['fresh'])==proof['dirty'],(p,'typed dirty roster'))
        assert x[0]['argv']==proof['argv'] and len(set(e['seq'] for e in x))==len(x)
        assert all(e['pid']>0 and isinstance(e['cdhash'],str) for e in x)
        main=[e for e in x if e['argv'][1:]==proof['argv'][2:] and L(e['path']).name in {'cargo','cargo-293'}
              and e['path'].endswith(('/native/bin/cargo','/cargo-293','/signed/bin/cargo'))]
        assertat(len(main)==1,(p,'root Cargo',[(e['path'],e['argv'][:3]) for e in x if e['argv'][1:]==proof['argv'][2:]]))
        aliases=[e for e in x if e['argv'] and L(e['argv'][0]).name=='ohm-link-cc' and
                 L(e['argv'][0]).parent.suffix=='.rlink-objects' and e['cdhash']==main[0]['cdhash']]
        full=[];linkonly=[]
        for e in x:
            a=e['argv']
            if '--crate-name' not in a or not e['path'].endswith('/native/bin/rustc'):continue
            c=a[a.index('--crate-name')+1]
            if c=='___' and any(s=='--print' or s.startswith('--print=') for s in a):continue
            (linkonly if any('link-only' in arg for arg in a) else full).append(c)
        ld=[e for e in x if L(e['path']).name in LD]
        native=proof['native']
        assertat(native['scope']=='kernel-exec' and native['cargo']==1,(p,'kernel'))
        assertat(sorted(full)==native['full'] and sorted(linkonly)==native['link_only'],(p,'compiler',full,linkonly))
        assertat([e['argv'] for e in ld]==[r['argv'] for r in native['linkers']],(p,'linker'))
        assertat([e['pid'] for e in aliases]==[r['pid'] for r in native['cargo_link_driver']],(p,'driver'))
        assert all(v['stock'] and '/Xcode' in e['path'] for e,v in zip(ld,native['linkers']))
        ident={(e['cdhash'],v['sha']) for e,v in zip(ld,native['linkers'])};self.lds.update(ident)
        r=self.js(p+'/native-link-receipt.json')
        assertat(r['full']==sorted(full) and r['link_only']==sorted(linkonly) and r['stock_links']==len(ld),(p,'native census'))
        assert r['ld_dependency_info']==sum('-dependency_info' in e['argv'] for e in ld)
        assert r['clang_dry_run_pids']==[e['pid'] for e in x if '-###' in e['argv']]
        seals=set();products=set()
        for a,v in r['aliases'].items():
            assert L(a).name=='ohm-link-cc' and L(a).parent.suffix=='.rlink-objects'
            f=v['records']
            if 'seal' in f:
                data=bytes.fromhex(f['seal']['hex'])
                assert 32<=len(data)<=65568 and sha(data)==f['seal']['sha256']
                assert 'product' in f
                seals.add(f['seal']['sha256']);products.add(f['product']['sha256'])
        bs=[e for e in x if L(e['path']).name.startswith(('build-script','build_script'))]
        desc={'status':proof['status'],'full':sorted(full),'link_only':sorted(linkonly),'ld':len(ld),
              'cargo_cdhash':main[0]['cdhash'],'driver_processes':len(aliases),'dry_clangs':len(r['clang_dry_run_pids']),
              'dependency_info':r['ld_dependency_info'],'seals':sorted(seals),'receipt_products':sorted(products),
              'build_scripts':len(bs),'streams':digests}
        return desc,cargo,out,err,ld
    def provider_visit(self,p,placement):
        proof=self.js(p+'/verified.json')
        d,events,stdout,stderr,ld=self.actual(p,'provider',proof)
        roots=[e for e in ld if '-lqa_owned_external' in e['argv'] or
               placement=='registrybundle' and '-o' in e['argv'] and L(e['argv'][e['argv'].index('-o')+1]).name.startswith('qa_owned_test')]
        assertat([e['pid'] for e in roots]==[r['pid'] for r in proof['final_links']],(p,'final links'))
        for e in roots:
            a=e['argv'];dirs=[L(v[2:] if v!='-L' else a[i+1]).name for i,v in enumerate(a) if v.startswith('-L')]
            assert 'early' in dirs and 'late' in dirs and dirs.index('early')<dirs.index('late')
        d['final']=len(roots);d['answer']=None;d['raw']=None
        units=[e for e in events if e['reason']=='compiler-artifact']
        d['registry']=sorted(set((v['target']['name'],v['package_id'].startswith('registry+')) for v in units if v['target']['name']=='barrier'))
        d['typed_dirty']=sorted(e['target']['name'] for e in units if not e['fresh'])
        if d['status']==0:
            true=self.gz(p+'/program.stdout.gz');assert not self.gz(p+'/program.stderr.gz')
            assert re.fullmatch(rb'(17|29) (7|11|13|15|19)\n',true)
            prog=self.js(p+'/program.json');assert prog['exit']==0
            exe,=[r['executable'] for r in units if r['target']['name']=='qa_owned_test' and r['executable']]
            d['raw']=prog['sha256'];d['answer']=[int(v) for v in true.split()]
            assert d['answer']==proof['answer'] and exe==prog['path'] and prog['sha256']==proof['image']['raw']
            if self.complete:assert self.product('edge-images',d['raw'])==proof['image']
            assert all(k['output_sha'] in (None,d['raw']) for k in proof['final_links'])
        else:
            assert d['status']==101 and proof['image'] is None and (b'qa_owned_external' in stdout+stderr or b'qa_value' in stdout+stderr)
            known=[e['message'].get('rendered') or '' for e in events if e['reason']=='compiler-message']+[stderr.decode(errors='replace')]
            d['error']=' | '.join(re.sub(r'/[^ ,\n]+','<path>',ln.strip())[:200] for txt in known for ln in txt.splitlines()
                                  if re.search(r"unknown file type|library 'qa_owned_external' not found|could not find native static library|failed to add native library|file format not recognized|not a valid archive|Undefined symbols",ln,re.I))[:420]
        if self.complete:
            mm=set()
            for v in proof['marker'].values():
                data=self.gz('edge-markers/'+v['sha256']+'.d.gz')
                assert sha(data)==v['sha256'] and v['hard']==(b'ohm-untracked-relink-inputs' in data) and v['recheck']==(b'/dev/null/ohm-recheck-dependent-links' in data)
                mm.add((v['hard'],v['recheck']))
            d['depfile_marker_bits']=sorted(mm)
        if placement=='registrybundle':
            bs=self.js(p+'/bundled-archive.json')
            d['bundled']=[{'id':v['id'],'rlib':v['rlib'],'providers':v['providers']} for v in bs]
            assert d['status']!=0 or len(bs)==1 and all(r['id'].startswith('registry+') for r in bs)
        return d
    def case(self,name):
        pref='provider-matrix/'+name;meta=self.js(pref+'/inputs.json')
        typ,placement,policy,mode=name.split('-');fl=meta['source']
        assert meta['role']==typ[0] and meta['defaults']==(mode=='default') and meta['placement']==placement and meta['watch']==policy
        assert sum(v.count('::asm!') for f,v in fl.items() if f.endswith('.rs'))==1
        body=fl['src/main.rs' if placement=='direct' else 'barrier/src/lib.rs']
        assert '::asm!("crc32w {v:w}, {v:w}, {d:w}", v = inout(reg) value, d = in(reg) data);' in body
        assert '#[target_feature(enable="crc")]' in body and 'checked_crc(0, 0)' in body
        assert ('rerun-if-changed={name}' in fl['build.rs'])==(policy=='declared')
        top=self.js(pref+'/terminal.json')
        rows={}
        prior={}
        for stage,state,rust in meta['steps']:
            d=pref+'/'+stage;a=self.provider_visit(d+'/warm',placement);b=self.provider_visit(d+'/empty',placement)
            comp=self.js(d+'/compared.json');assert comp==top[stage] and comp['rust']==rust and comp['trigger_sha256']==sha(('#[inline(never)] pub fn value()->i32 {'+str(rust)+'}\n').encode())
            assert comp['warm']==[a['status'],a['answer'],a['raw']] and comp['empty']==[b['status'],b['answer'],b['raw']]
            val={'lower':17,'higher':29,'overwrite':17,'restore':29}.get(state)
            assert (b['status'],b['answer'])==((0,[val,rust]) if val else (101,None)),(name,stage,'empty behavior')
            item={'warm':a,'empty':b,'input':{k:comp['archives'][k] for k in ('early','late')},
                  'same_verdict':(a['status'],a['answer'])==(b['status'],b['answer']),
                  'same_raw':(a['raw']==b['raw']) if a['raw'] and b['raw'] else None,
                  'trigger':comp['trigger_sha256']}
            if 'modification' in comp['archives']:
                item['stamp']={k:v for k,v in comp['archives'].items() if k not in ('early','late')}
            assert item['same_raw']==comp['same_raw']
            equivalence=item['same_raw']
            if mode=='default':
                for end,visit in [('warm',a),('empty',b)]:
                    if visit['status']==0:
                        proof=self.image_proofs.proof(d+'/'+end,'edge-images',prior=prior if end=='warm' else None)
                        assert proof['raw']==visit['raw']
                        visit['image_witness']=proof
                if a['raw'] and b['raw']:
                    equivalence=self.image_proofs.same(a['image_witness'],b['image_witness'])
            item['same_checked_image']=equivalence
            assert comp['same_checked_image']==equivalence
            rows[stage]=item
        return rows
