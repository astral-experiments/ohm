"""Recount the independently captured native rosters, exact cargo/worker instructions and payloads."""
from pathlib import Path
import ast,gzip,hashlib,io,json,re,runpy,struct,sys,tarfile,zipfile
lib=runpy.run_path(str(Path(__file__).with_name('verify-ruff.py')))
H=lib['H']; emitted=lib['emitted']; members=lib['members']; recount=lib['recount']
HEAD='8ad9758f15746600982183222d339779dbac4715'
BEFORE='d3538b42a2dc56edb9bffbc9cc2373fb93c35054'; AFTER='f2edebc7a23b809749fb0cc44dd6ac902ca448ff'
OLD='1a8df04825085b4b606db458fecf9ec24f2b651414eea444670226a5dfbf72f9'
NEW='7d4d2fd48f2ef717f19b11cf5e4f21bcea69d16d55e631301b8266d74cf8abd8'
INV='fe68c95a764685c7677db770a5e302996d8a18b95ed8ccf7d054a320c979b6ac'
ids=lambda v:H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
keyfile=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
STR=rb'"(?:[^"\\]|\\.)*"'
ARRAY=rb'\[(?:'+STR+rb'(?:, '+STR+rb')*)?\]'
EXEC=re.compile(rb'^execve\(('+STR+rb'), ('+ARRAY+rb'), (?:NULL|0x[^)]*|'+ARRAY+rb')\)\s+= 0$')
class Study:
    def __init__(self, path):
        self.z=zipfile.ZipFile(path)
        self.all=set(self.z.namelist());assert len(self.all)==len(self.z.namelist())
        self.archives={};self.native_refs={};self.elf={}
    def get(self,p):return self.z.read(p)
    def J(self,p):return json.loads(self.get(p))
    def cmd(self,p):
        c=self.J(p+'/command.json');streams=[gzip.decompress(self.get(p+'/'+n+'.gz')) for n in ('stdout','stderr')]
        assert [H(o) for o in streams]==[c['stdout'],c['stderr']];return c,*streams
    def archive(self,p):
        k=p['raw']
        if k not in self.archives:
            b=self.get('objects/'+k+'.rlib');assert H(b)==k
            self.archives[k]=members(b)
        obs,md=self.archives[k]; assert obs==p['objects'] and md==p['metadata']
        return [[n,sz,h] for n,_,sz,h in obs]
    def native(self,folder,phase,expected):
        p=folder+'/'+phase
        v=self.J(p+'/verified.json');assert v['phase']==phase
        native=self.J(p+'/native.json');assert H(self.get(p+'/native.json'))==v['native']
        c,out,err=self.cmd(p+'/cargo');good=expected!='invalid'
        assert c['exit']==(0 if good else 101)
        events,inventory,dirty=emitted(out,good);assert inventory==v['typed'] and dirty==v['dirty']
        with tarfile.open(fileobj=io.BytesIO(self.get(p+'/exec.tar.gz'))) as tar:
            traces={int(f.name.rsplit('.',1)[1]):tar.extractfile(f).read() for f in tar if f.isfile()}
        for lab,rows in native.items():
            for row in rows:
                lines=traces[row['pid']].splitlines()
                assert any(m and ast.literal_eval(m[1].decode())==row['path'] and ast.literal_eval(m[2].decode())==row['argv'] for m in (EXEC.match(l) for l in lines))
                assert list(map(int,re.findall(rb'^\+\+\+ exited with (\d+) \+\+\+$',traces[row['pid']],re.M)))==row['terminal']
                if good:assert row['terminal']==[0]
        assert native['cargo'][0]['terminal']==[c['exit']]
        roster=sorted(r['crate'] for r in native['rustcs']);assert roster==sorted(v['crates'])
        dep=self.get(p+'/zmij.d'); assert H(dep)==v['marker']['sha256'] and (b'ohm-untracked-relink-inputs' in dep)==v['marker']['hard'] and (b'ohm-recheck-dependent-links' in dep)==v['marker']['recheck']
        summary={'code':c['exit'],'rustc':roster,'links':len(native['link_tools']),'probes':len(native['compiler_probes']),'dirty':dirty,'typed':len(inventory)}
        if not good:
            assert v['error']=='E0425' and b'apple_zmij_missing_name' in out and any((item['message'].get('code') or {}).get('code')=='E0425' for item in events if item['reason']=='compiler-message')
            return summary
        assert len(inventory)==39 and ids(inventory)==INV
        if p+'/unit-evidence.json' in self.all:
            units=self.J(p+'/unit-evidence.json');markers={}
            for crate in ('zmij','compact_str','ruff_python_ast'):
                u=units['units'][crate];raw=self.get(p+'/'+crate+'.d');mark=[b'ohm-untracked-relink-inputs' in raw,b'ohm-recheck-dependent-links' in raw]
                assert H(raw)==u['dep'] and mark==[u['hard'],u['recheck']] and u['argv'][u['argv'].index('--crate-name')+1]==crate
                markers[crate]=mark
            for fname,row in units['fingerprint_files'].items():
                h,*_,size=row;b=self.get(p+'/'+h+'.fingerprint');assert H(b)==h and len(b)==size
            assert markers==self.J(folder+'/native-markers.json')[phase];summary['markers']=markers
        cor,_,_=self.cmd(p+'/correct');con,_,stderr=self.cmd(p+'/contrary');elf,qemu,_=self.cmd(p+'/qemu')
        assert [cor['exit'],con['exit'],elf['exit']]==[0,1,0] and any((item.get('code') or {}).get('code')=='E0308' for item in map(json.loads,stderr.splitlines()))
        if expected=='old': h,answer=OLD,'3.14 3.14 3.10'
        else:h,answer=NEW,'3.15 3.15 3.11'
        assert qemu.decode()==answer+'\n' and v['value']==answer and v['reader']==h
        if h not in self.elf:
            raw=self.get('objects/'+h+'.elf');assert H(raw)==h and raw[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',raw,18)==(183,)
            self.elf[h]=len(raw)
        obj=self.archive(v['archive']);assert len(obj)==95 and self.native_refs.setdefault(expected,obj)==obj
        summary.update(reader=h,raw_archive=v['archive']['raw'],ordered_objects=ids(obj))
        return summary
    def count(self,root,actual,prior,stable):
        native=self.J(prior+'/native.json'); base=self.J(prior+'/verified.json')
        assert not native['compiler_probes'] and not native['link_tools']
        want={'cargo':native['cargo'][0]['argv']}|{r['crate']:r['argv'] for r in native['rustcs']}
        verify=self.J(actual+'/verified.json');record=self.J(root+'/observed.json')
        assert record=={k:verify[k] for k in ('Ir','processes')}
        desc=self.J(root+'/command/physical-jobserver.json');assert desc.keys()==want.keys()-{'cargo'}
        cap,out,err=self.cmd(root+'/command')
        _,inventory,dirty=emitted(out,True);assert inventory==base['typed'] and ids(inventory)==INV and dirty==base['dirty'] and cap['exit']==0
        if stable:
            pre=self.J(actual+'/physical.json')
            assert pre['roster'].keys()==want.keys() and all(pre['roster'][r]['argv']==want[r] for r in want)
            assert verify['compiler_subtotal']==sum(v['Ir'] for n,v in record['processes'].items() if n!='cargo')
        else:
            assert H(self.get(root+'/command/physical-jobserver.json'))==verify['physical_jobserver']
            assert H(self.get(prior+'/native.json'))==verify['prior_raw_native'] and verify['typed']==inventory and verify['dirty']==dirty
            assert self.archive(verify['archive'])==self.native_refs['edited']
        assert record['processes'].keys()==want.keys();observed={};prefix=root+'/profiles/';pids=set()
        for lab,r in record['processes'].items():
            pid=r['pid'];pids.add(pid);assert r['argv']==want[lab]
            logs=self.get(prefix+'log.'+str(pid));b=gzip.decompress(self.get(prefix+'cg.'+str(pid)+'.gz'))
            assert H(b)==r['profile'] and H(logs)==r['log']
            if lab!='cargo':
                d=desc[lab];assert pid==d['pid'] and re.fullmatch(r'pipe:\[\d+\]',d['pipe']) and len(set(d['descriptor_numbers']))==2
            observed[lab]=recount(b,logs,pid,r['argv']);assert observed[lab]==r['Ir']
        assert {p for p in self.all if p.startswith(prefix+'cg.')}=={prefix+'cg.'+str(pid)+'.gz' for pid in pids}
        assert {p for p in self.all if p.startswith(prefix+'log.') and self.z.getinfo(p).file_size}=={prefix+'log.'+str(pid) for pid in pids}
        assert sum(observed.values())==verify['Ir']
        return observed

def main(run):
    f=run/'gnu-compact-input-ruff-complete.zip';a=Study(f);t=a.J('terminal.json'); s=a.J('subjects.json');wf=json.loads((run/'workflow.json').read_bytes())
    assert wf['headSha']==HEAD==a.get('qa-head').decode().strip() and wf['conclusion']=='success' and wf['status']=='completed'
    assert s['source']==[BEFORE,AFTER] and s['driver']['P']=='a51424740c111a4cfdfc67b39bf498907eb396b4b1f0800c27c4fcafc9e6eb72'
    artifact,=[x for x in json.loads((run/'artifacts.json').read_bytes())['artifacts'] if x['name']=='gnu-compact-input-ruff-complete']; raw=keyfile(f);assert 'sha256:'+raw==artifact['digest']
    table={}; native={};counts={};retained={}
    for label in ('mirror1-P','mirror1-C','mirror2-C','mirror2-P'):
        phases={p:a.native(label,p,'invalid' if p=='invalid' else 'old' if p=='old-empty' else 'edited') for p in lib['PHASES']}
        arm=label[-1];cycle=label+'-edit-cycle';new={}
        new['old-empty']=a.native(cycle,'old-empty','old');new['post-settled']=a.native(cycle,'post-settled','edited')
        counts[label]={'settled':a.count(label+'/counter/whole',label+'/counter',label+'/unchanged-1',True)}
        for n,orig in [('first-real-edit','edit'),('immediate-repeat','unchanged-1')]:counts[label][n]=a.count(cycle+'/'+n,cycle+'/'+n,label+'/'+orig,False)
        for name in ('unchanged-1','unchanged-2'):
            assert set(phases[name]['rustc'])==({'compact_str','ruff_python_ast'} if arm=='P' else set()) and not phases[name]['links']
            for crate in ('ruff_python_ast','compact_str'):assert phases[name]['markers'][crate]==([True,False] if arm=='P' else [False,True])
        assert set(phases['edit']['rustc'])==({'compact_str','ruff_python_ast'} if arm=='P' else {'ruff_python_ast'})
        native[label]=phases;retained[label]=new
    for m in ('mirror1','mirror2'):
        top=lambda role,stage:sum(counts[m+'-'+role][stage].values())
        row={'settled_ratio':top('P','settled')/top('C','settled'),'actual_edit_ratio':top('P','first-real-edit')/top('C','first-real-edit'),
             'edit_and_next_ratio':(top('P','first-real-edit')+top('P','immediate-repeat'))/(top('C','first-real-edit')+top('C','immediate-repeat'))}
        assert all(row[k]==t['both_mirrors'][m][k] for k in row) and t['both_mirrors'][m]['native_gate']
        table[m]=row
    assert all(x['settled_ratio']>2 for x in table.values())==t['settled_meets_two']
    assert all(x['edit_and_next_ratio']>2 for x in table.values())==t['two_command_cycle_meets_two']
    evidence={'source':[BEFORE,AFTER],'action':HEAD,'native':native,'counted_cycle_independent_native':retained,'complete_guest_Ir':counts,'ratios':table,
          'old_and_edited_complete_ELF':a.elf,'all_ordered_object_payloads':{k:[len(v),ids(v)] for k,v in a.native_refs.items()},
          'complete_raw_archives':sorted(a.archives),'typed':INV,'original_terminal':H(a.get('terminal.json')),'raw_return':raw,'preexisting_component_excluded':'41062797687'}
    body=(json.dumps(evidence,indent=2,sort_keys=True)+'\n').encode();(run/'fully-reopened.json').open('xb').write(body);print(H(body),table)
if __name__=='__main__':main(Path(sys.argv[1]))
