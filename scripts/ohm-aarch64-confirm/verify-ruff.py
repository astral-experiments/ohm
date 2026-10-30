"""Check every registered native visit, source outcome and complete process profile in a returned run."""
from collections import Counter
import ast, gzip, hashlib, io, json, re, struct, sys, tarfile, zipfile
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
BASE="444c0273a2e2bc0b161e988d43c882349bc2d7a6";N="d3538b42a2dc56edb9bffbc9cc2373fb93c35054"
PHASES=("old-empty","edit","unchanged-1","unchanged-2","invalid","repair","empty-edited")
def members(raw):
    assert raw.startswith(b'!<arch>\n');p=8;long=b'';ans=[];meta={}
    while p<len(raw):
        head=raw[p:p+60];sz=int(head[48:58]);name=head[:16].rstrip();b=raw[p+60:p+60+sz];assert head[58:]==b'`\n' and len(b)==sz
        if name==b'//':long=b
        elif name.startswith(b'/') and name[1:].isdigit():start=int(name[1:]);name=long[start:long.index(b'/\n',start)]
        else:name=name.removesuffix(b'/')
        if name.endswith(b'.o'):
            assert b[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<HH',b,16)==(1,183)
            display=name.decode();canon=re.sub(r'\.[0-9a-z]{7}(?=\.rcgu\.o$)','.<rustc-session>',display);ans.append([canon,display,sz,H(b)])
        elif name in (b'lib.rmeta',b'lib.rmeta-link'):meta[name.decode()]=[sz,H(b)]
        p+=60+sz+(sz&1)
    assert p==len(raw) and ans and len(ans)==len({row[0] for row in ans}) and 'lib.rmeta' in meta
    return ans,meta

def recount(raw,log,pid,argv):
    pid_rx=rb'^=='+str(pid).encode()+rb'== ';assert raw.splitlines().count(b'pid: '+str(pid).encode())==1
    assert raw.splitlines().count(b'cmd:  '+b' '.join(x.encode() for x in argv))==1 or re.findall(rb'^cmd:\s*(.*?)\s*$',raw,re.M)==[b' '.join(x.encode() for x in argv)]
    assert re.findall(rb'^events: (.*)$',raw,re.M)==[b'Ir']
    total=0;edge=False
    for line in raw.splitlines():
        if line.startswith(b'calls='):
            assert not edge;edge=True
        elif re.match(rb'^[*+\-\d]',line):
            if not edge:total+=int(line.split()[-1])
            edge=False
    assert not edge and list(map(int,re.findall(rb'^totals: (\d+)$',raw,re.M)))==[total]
    numbers=re.findall(pid_rx+rb'Collected\s+:\s+([\d,]+)\s*$',log,re.M)
    assert numbers==[next(iter(numbers))] and int(numbers[0].replace(b',',b''))==total
    return total

def emitted(raw,good):
    e=list(map(json.loads,raw.splitlines()));assert e[-1]=={'reason':'build-finished','success':good}
    builds=[k for k in e if k['reason']=='compiler-artifact'];dirty=sorted(k['target']['name'] for k in builds if not k['fresh'])
    ids=sorted([[k["package_id"],k["target"]["name"],k["target"]["kind"],sorted(k["features"]),k["profile"]] for k in builds],key=json.dumps)
    return e,ids,dirty

def main(run):
    zip_path=run/'gnu-register-ruff-screen.zip';z=zipfile.ZipFile(zip_path);data=z.read; J=lambda n:json.loads(data(n)); info=json.loads((run/'workflow.json').read_bytes()); art,=[a for a in json.loads((run/'artifacts.json').read_bytes())['artifacts'] if a['name']=='gnu-register-ruff-screen']
    assert art['digest']=='sha256:'+hashlib.file_digest(zip_path.open('rb'),'sha256').hexdigest()
    assert info['headSha'].encode()==data('qa-head').strip()
    def cmd(p):
        c=J(p+'/command.json');o,e=[gzip.decompress(data(p+'/'+n+'.gz')) for n in ('stdout','stderr')];assert [H(o),H(e)]==[c['stdout'],c['stderr']];return c['exit'],o,e
    sub=J('subjects.json');assert (sub['base'],sub['treatment'])==(BASE,N)
    roles=[('mirror1-P','P'),('mirror1-C','C'),('mirror2-C','C'),('mirror2-P','P')]
    returns={};per={};all_native={};seen_objects={};originals={};edited={};invent=None;components={}
    for label,role in roles:
        result={};per[label]={}; table=J(label+'/complete.json');assert table['role']==role
        for state in PHASES:
            p=label+'/'+state; v=J(p+'/verified.json');native=J(p+'/native.json');assert v['phase']==state and H(data(p+'/native.json'))==v['native']
            status,out,err=cmd(p+'/cargo');valid=state!='invalid';assert status==(0 if valid else 101)
            events,ids,dirty=emitted(out,valid);assert ids==v['typed'] and dirty==v['dirty']
            assert native['cargo'][0]['terminal']==[status]
            raw_traces={}
            with tarfile.open(fileobj=io.BytesIO(data(p+'/exec.tar.gz'))) as t:
                for j in t:
                    if j.isfile():raw_traces[int(j.name.rsplit('.',1)[1])]=t.extractfile(j).read()
            for row in [*native['cargo'],*native['rustcs'],*native['link_tools'],*native['compiler_probes']]:
                if valid:assert row['terminal']==[0]
                lines=raw_traces[row['pid']].splitlines()
                matches=[x for x in lines if x.startswith(b'execve(') and x.endswith(b'= 0')]
                identified=False
                for x in matches:
                    m=re.fullmatch(rb'execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0',x)
                    if m and ast.literal_eval(m[1].decode())==row['path'] and ast.literal_eval(m[2].decode())==row['argv']:identified=True
                assert identified
            roster=sorted(k['crate'] for k in native['rustcs']);assert roster==sorted(v['crates'])
            per[label][state]={'rustcs':len(roster),'selected_rustcs':[c for c in roster if c in ('zmij','compact_str','ruff_python_ast')],
                              'link_processes':len(native['link_tools']),'other_compiler_probes':len(native['compiler_probes']),'cargo_typed_dirty':dirty,'typed_units':len(ids)}
            dep=data(p+'/zmij.d');assert H(dep)==v['marker']['sha256'] and (b'ohm-untracked-relink-inputs' in dep)==v['marker']['hard'] and (b'/dev/null/ohm-recheck-dependent-links' in dep)==v['marker']['recheck']
            if not valid:
                assert v['error']=='E0425' and b'apple_zmij_missing_name' in out and any(e.get('message',{}).get('code',{}).get('code')=='E0425' for e in events if e.get('reason')=='compiler-message' and e['message'].get('code'));continue
            if invent is None:invent=ids
            assert invent==ids and len(ids)>10 and (cmd(p+'/correct')[0],cmd(p+'/contrary')[0])==(0,1)
            _,_,contrary=cmd(p+'/contrary');assert any(e.get('code',{}).get('code')=='E0308' for e in map(json.loads,contrary.splitlines()) if e.get('code'))
            rc,qemu,_=cmd(p+'/qemu');wanted=b'3.14 3.14 3.10\n' if state=='old-empty' else b'3.15 3.15 3.11\n'
            assert rc==0 and qemu==wanted and v['value']==wanted.decode().strip()
            if v['reader'] not in seen_objects:
                b=data('objects/'+v['reader']+'.elf');assert H(b)==v['reader'] and b[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',b,18)[0]==183;seen_objects[v['reader']]='elf'
            arch=v['archive'];k=arch['raw']
            if k not in seen_objects:
                original=data('objects/'+k+'.rlib');assert H(original)==k;obs,md=members(original);assert obs==arch['objects'] and md==arch['metadata'];seen_objects[k]='rlib'
            # Whole ordered underlying object bodies and exact names separately retained.
            sig={'elf':v['reader'],'object_signature':H(json.dumps([[n,s,h] for n,_,s,h in arch['objects']],separators=(',',':')).encode()),'count':len(arch['objects']),'qemu':wanted.decode().strip()}
            result[state]=sig;components[label+'/'+state]=[k,arch['metadata']]
        echo=result['empty-edited'];assert all(result[state]==echo for state in ('edit','unchanged-1','unchanged-2','repair'))
        originals[label]=result['old-empty'];edited[label]=echo
        v=J(label+'/counter/verified.json'); pre=J(label+'/counter/physical.json');execs=J(label+'/unchanged-1/native.json')
        fds=J(label+'/counter/whole/command/physical-jobserver.json')
        want={'cargo':execs['cargo'][0]['argv']}|{b['crate']:b['argv'] for b in execs['rustcs']}
        assert v['processes'].keys()==pre['roster'].keys()==want.keys() and fds.keys()==want.keys()-{'cargo'} and not execs['link_tools'] and not execs['compiler_probes']
        val={}
        for n,row in v['processes'].items():
            pid=row['pid'];p=label+'/counter/whole/profiles/';raw=gzip.decompress(data(p+'cg.'+str(pid)+'.gz'));logs=data(p+'log.'+str(pid))
            assert H(raw)==row['profile'] and H(logs)==row['log'] and row['argv']==want[n]==pre['roster'][n]['argv']
            if n!='cargo':assert pid==fds[n]['pid'] and re.fullmatch(r'pipe:\[\d+\]',fds[n]['pipe']) and len(set(fds[n]['descriptor_numbers']))==2
            val[n]=recount(raw,logs,pid,row['argv']);assert val[n]==row['Ir']
        expected_profiles={label+'/counter/whole/profiles/cg.'+str(x['pid'])+'.gz' for x in v['processes'].values()}
        assert expected_profiles=={p for p in z.namelist() if p.startswith(label+'/counter/whole/profiles/cg.')}
        assert sum(val.values())==v['Ir'] and sum(c for n,c in val.items() if n!='cargo')==v['compiler_subtotal']
        all_native[label]=val; returns[label]=v['Ir']
    assert len({v['elf'] for v in originals.values()})==len({v['elf'] for v in edited.values()})==1 and originals['mirror1-P']!=edited['mirror1-P']
    assert len({v['object_signature'] for v in originals.values()})==len({v['object_signature'] for v in edited.values()})==1
    for mirror in ('mirror1','mirror2'):
        for state in ('unchanged-1','unchanged-2'):
            pa,ne=[per[mirror+'-'+r][state] for r in 'PC']
            assert 'zmij' in pa['selected_rustcs'] and 'zmij' not in ne['selected_rustcs'] and ne['rustcs']<pa['rustcs'] and ne['link_processes']==pa['link_processes']==0
    ratios={m:returns[m+'-P']/returns[m+'-C'] for m in ('mirror1','mirror2')}
    terminal=J('independent-terminal.json');assert ratios==terminal['two_independent_mirrors'] and all(x>2 for x in ratios.values())==terminal['all_ratios_above_two']
    return {'run':run.name,'workflow':info['headSha'],'original_terminal':H(data('independent-terminal.json')),'raw':art['digest'],'sources':[BASE,N],
            'typed_inventory':H(json.dumps(invent,sort_keys=True,separators=(',',':')).encode()),'typed_units':len(invent),
            'Ir_per_process':all_native,'total_complete_Ir':returns,'parent_over_candidate':ratios,'native':per,'old_elf_and_object':originals,'edited_elf_and_object':edited,'all_raw_archive_hashes':components}
if __name__=='__main__':
    p=Path(sys.argv[1]);r=main(p);buf=(json.dumps(r,sort_keys=True,indent=2)+'\n').encode();(p/'independent.json').open('xb').write(buf);print(H(buf),r['Ir_per_process'],r['parent_over_candidate'])
