"""Measure the actual signed Ruff args object by named receiver, binding and real payload."""
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from read_objects import Elf, members, need
from rustc_name import sip

def cgu_name(name):
    h=sip(name.encode()+b'\xff');n=int(h[16:]+h[:16],16);s=''
    while n:n,k=divmod(n,36);s='0123456789abcdefghijklmnopqrstuvwxyz'[k]+s
    return s.rjust(25,'0')
def main(archive,digest,out):
    with archive.open('rb')as f:need(hashlib.file_digest(f,'sha256').hexdigest()==digest,'source original')
    with zipfile.ZipFile(archive)as z:
        kid='26b50y1455r2nn7imncnrh1im';vid='3xhp4sunmhbswr1ovpiqoyj96'
        ss=json.loads(z.read('old/incremental-native-sessions.json'));unit,=[k.split('/')[-2]for k,v in ss.items()if len(v)==236]
        stable=int(unit.removeprefix('ruff-'),36)
        a_name=f'ruff.{stable:08x}-args';v_name=f'ruff.{stable:08x}-version'
        need(cgu_name(a_name)==kid and cgu_name(v_name)==vid,'original unsplit local module identities')
        ms=members(z,'old');rank=sorted(ms,key=lambda k:-ms[k][1]).index(kid)+1
        group=collections.defaultdict(list);raw=[]
        for ph in ('old','edit'):
            use=members(z,ph)[kid][0];b=subprocess.check_output(['zstd','-dcq'],input=z.read('four-native-bodies/'+use+'.zst'))
            need(hashlib.sha256(b).hexdigest()==use,'ELF identity');raw.append(Elf(b))
        a,b=raw;fns=sorted(a.functions)
        names=subprocess.check_output(['c++filt','-n'],input=('\n'.join(x[0]for x in fns)+'\n').encode()).decode().splitlines()
        need(len(names)==len(fns)==125 and a.functions.keys()==b.functions.keys(),'typed functions')
        changes=[]
        for i,n in zip(fns,names):
            n=re.sub(r'\[[a-f0-9]{8,16}\]','',n);left,rl=a.functions[i];right,rr=b.functions[i];need(rl==rr and len(left)==len(right),'reloc- and size-invariant methods')
            m=re.fullmatch(r'<ruff::args::([A-Za-z0-9_]+) as clap_builder::derive::(Args|FromArgMatches|Subcommand|CommandFactory)>::(.+)',n)
            owner=m[1] if m else 'other'
            group[owner].append({'method':n,'bytes':len(left),'binding':i[1]>>4})
            delta=[[j,x,y]for j,(x,y)in enumerate(zip(left,right))if x!=y]
            if delta:
                need(left[647:652]==bytes.fromhex('ba e1 01 00 00') and right[647:652]==bytes.fromhex('ba dc 01 00 00'),'actual x86-64 mov $481/$476,%edx')
                changes.append({'method':n,'bytes':len(left),'different_bytes':delta})
        need(len(changes)==2 and all(len(v['different_bytes'])==1 and 'GlobalConfigArgs' in v['method']for v in changes),'typed real changed methods')
        rokeys=[i for i,s in enumerate(a.secs)if s[2]&2 and b'--config "lint.line-length = 100"'in a.blob(s)]
        need(len(rokeys)==1,'unique OLD literal section');i=rokeys[0];key=a.keys[i];j=b.keys.index(key)
        oldblob=a.blob(a.secs[i]);newblob=b.blob(b.secs[j]);literal=b'--config "lint.line-length = 100"';fixed=literal.replace(b'lint.',b'')
        need(oldblob.count(literal)==newblob.count(fixed)==1 and oldblob.replace(literal,fixed)==newblob,'literal-only section replacement')
        by={k:{'methods':len(v),'native_bytes':sum(i['bytes']for i in v),'global_definitions':sum(i['binding']==1 for i in v)}for k,v in group.items()}
        result={'archive':digest,'actual_machine_module':a_name,'separate_changed_version_module':v_name,'library_cgus':len(ms),'args_rank_by_full_object_size':rank,'args_size':ms[kid][1],
                'all_native_function_bytes':sum(x['native_bytes']for x in by.values()),'by_named_clap_receiver':by,'exact_machine_byte_edits':changes,'separate_help_literal_section':{'section':key,'old_bytes':len(oldblob),'new_bytes':len(newblob)},'methods':group}
        out.write_text(json.dumps(result,sort_keys=True,indent=1)+'\n')
        print(a_name,rank,by['GlobalConfigArgs'],changes,result['separate_help_literal_section'])
if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]))
