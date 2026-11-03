"""Check every modified resolved slot against both dlsym(driver,name) and the observed executable mapping."""
from pathlib import Path
import ctypes as ct,gzip,hashlib,json,os,subprocess as sp,sys
P=Path(__file__).resolve().parent;K=P.parent;SDK=K.parent/'release-23-uv-22958/proposal-255/actual-published-23/signed-sdk';reg=json.loads((P/'patch.json').read_bytes());c=gzip.decompress((P/'rows.json.gz').read_bytes());assert hashlib.sha256(c).hexdigest()==reg['uncompressed_rows'];rows=json.loads(c)
sha=lambda p:hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
# This name comes from one genuine original compiler-private formatting routine. No test calls it.
sel=next(r for r in rows if r['compiler_crates']==['rustc_mir_transform']and r['name'].endswith('3fmt')and r['original_kind']==6 and r['addend']==0)
def run(driver,preloaded,mutant):
 assert sha(driver)==reg['prototype'if mutant else'original'];lib=ct.CDLL(str(driver),mode=os.RTLD_NOW|os.RTLD_GLOBAL);libc=ct.CDLL(None);fn=libc.dlsym;fn.argtypes=(ct.c_void_p,ct.c_char_p);fn.restype=ct.c_void_p
 dl=libc.dlinfo;dl.argtypes=(ct.c_void_p,ct.c_int,ct.POINTER(ct.c_void_p));dt=ct.c_void_p();assert dl(lib._handle,2,ct.byref(dt))==0;bias=ct.c_size_t.from_address(dt.value).value;assert bias>0
 pathmaps=[]
 for l in Path('/proc/self/maps').read_text().splitlines():
    r,perms,off,_,_,*rest=l.split();lo,hi=map(lambda x:int(x,16),r.split('-'));pathmaps.append((lo,hi,perms,int(off,16),' '.join(rest)))
 cache={};checked=[];hits=0;foreign=None
 if preloaded:
    so=ct.CDLL(os.environ['LD_PRELOAD'].split(':')[0]);foreign=fn(so._handle,sel['name'].encode());assert foreign and foreign!=bias+sel['local_value']and fn(None,sel['name'].encode())==foreign
 for r in rows:
    sym=r['name'];value=cache.get(sym)
    if value is None:
        value=fn(lib._handle,sym.encode());assert value==bias+r['local_value'];cache[sym]=value
        region,=[z for z in pathmaps if z[0]<=value<z[1]];assert region[2][2]=='x'and os.path.samefile(region[4],driver)
    address=bias+r['target'];tar,=[z for z in pathmaps if z[0]<=address and address+8<=z[1]];assert tar[2].startswith('r--')and os.path.samefile(tar[4],driver)
    resolved=ct.c_uint64.from_address(address).value;wanted=value+(r['addend']if r['original_kind']==1 else 0)
    if preloaded and sym==sel['name']:
        hits+=1
        if not mutant:wanted=foreign+(r['addend']if r['original_kind']==1 else 0)
    assert resolved==wanted,(sym,r['i'],hex(resolved),hex(wanted))
    checked.append([r['i'],r['target'],r['local_value'],r['bound'],r['target']-tar[0]+bias+tar[3],tar[2],r['code_section'],('override'if preloaded and not mutant and sym==sel['name'] else 'driver')])
 assert len(checked)==8733 and len(cache)==7516 and ((hits>0)==preloaded)
 doc={'role':'prototype'if mutant else'signed','preload':preloaded,'exported_override_won_in_RTLD_DEFAULT':bool(preloaded),'selected_symbol':sel['name'],'selected_slot_count':hits,'driver':sha(driver),'original_rows':reg['rows'],'all_slots':len(checked),'all_exports':len(cache),'all_slot_runtime_permissions':['r--p'],'normalized_loaded_slot':checked}
 data=(json.dumps(doc,separators=(',',':'),sort_keys=True)+'\n').encode();out=P/('audit-'+doc['role']+('-preload'if preloaded else'')+'.json.gz');out.write_bytes(gzip.compress(data,mtime=0));print(out.name,len(checked),len(cache),hits)
if __name__=='__main__':
 if sys.argv[1]=='inside':run(Path(sys.argv[2]),sys.argv[3]=='1',sys.argv[4]=='1')
 else:
    source=P/'preload.c';source.write_text('void observer(void) __asm__("'+sel['name']+'");\nvoid observer(void) {}\n');so=P/'preload.so';sp.run(['cc','-shared','-fPIC','-Wl,-z,relro,-z,now',str(source),'-o',str(so)],check=True)
    for mutate in (False,True):
        for preload in(False,True):
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','LD_LIBRARY_PATH':str(SDK/'lib')}
            driver=P/'private-driver.so'if mutate else SDK/reg['driver']
            # The real driver has hundreds of initial-exec TLS imports and must join the start-up image.
            env['LD_PRELOAD']=(str(so)+':' if preload else '')+str(driver)
            sp.run(['/usr/bin/python3','-ISB',str(Path(__file__).resolve()),'inside',str(driver),str(int(preload)),str(int(mutate))],check=True,env=env)
