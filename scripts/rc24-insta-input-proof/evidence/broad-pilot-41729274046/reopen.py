"""Reopen GitHub's two sealed original hardware packets. No compiler or repository needed."""
import argparse,collections,hashlib,json,zipfile
from pathlib import Path

def sha(x):return hashlib.sha256(x).hexdigest()
def hardware(j):
    assert j['status']==0 and j['instructions']>0 and j['enabled']==j['running']>0
    return j['instructions']
def reopen(path,art,plan,expected):
    assert path.stat().st_size==art['size_in_bytes']
    with path.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==art['digest'].removeprefix('sha256:')
    with zipfile.ZipFile(path)as z:
        names=set(z.namelist());assert len(names)==len(z.infolist())and z.testzip()is None
        def read(n):return json.loads(z.read(n))
        def lines(n):return [json.loads(l)for l in z.read(n).splitlines()if l.startswith(b'{')]
        adm=read('admission.json');r=read('result.json')
        assert adm['head']==expected['head'] and adm['order']==plan['orders'][path.stem]
        assert adm['release']==expected['release'] and adm['source']==expected['new'] and adm['old']==expected['old']
        assert adm['pair']['qa']==plan['producer_head'] and int(adm['pair']['run'])==plan['producer_run']
        assert all(adm['pair']['cargo'][a]['sha256']==plan['cargo'][a]for a in ('parent','candidate'))
        assert 1.99<hardware(read('calibration-fork.json'))/hardware(read('calibration-single.json'))<2.01
        out=dict(boot=adm['boot'],archives=len(adm['archives']),archive_set=sha(json.dumps(adm['archives'],sort_keys=True).encode()),roles={})
        for arm in ('parent','candidate'):
            dirs=sorted({n.split('/')[1]for n in names if n.startswith(arm+'/')and n.endswith('/verdict.json')})
            counts={};natives={};invalid=[];actual=[];execution=[]
            for label in dirs:
                p=arm+'/'+label+'/';v=read(p+'verdict.json');msgs=lines(p+'stdout.jsonl')
                if label in ('invalid','invalid-again'):
                    es=[m['message']for m in msgs if m['reason']=='compiler-message'and m['message']['level']=='error']
                    assert msgs[-1]=={'reason':'build-finished','success':False}and v['exit']==101
                    assert any((m.get('code')or{}).get('code')=='E0308'and any(s['is_primary']and s['file_name'].endswith('/insta-1.48.0/src/settings.rs')for s in m['spans'])for m in es);invalid.append(label);continue
                assert msgs[-1]=={'reason':'build-finished','success':True};arts=[m for m in msgs if m['reason']=='compiler-artifact']
                assert len(arts)==v['total_units'] and [m['target']['name']for m in arts if not m['fresh']]==v['scheduled']
                assert v['argv'][:2]==['cargo','+ohm'] and '-j4'in v['argv'] and '--offline'in v['argv'] and '--locked'in v['argv']
                if p+'hardware.json'in names:
                    counts[label]=hardware(read(p+'hardware.json'));assert counts[label]==v['instructions'] and p+'tasks/epochs.tsv'not in names
                if p+'native.list'in names:
                    nl=z.read(p+'native.list');tests=sorted(l[:-6]for l in nl.decode().splitlines()if l.endswith(': test'))
                    assert len(tests)==(77 if v['head']==adm['old']else 78);assert sha(nl)==v['native_list_sha256']
                    nr=z.read(p+'native.result')if p+'native.result'in names else b''
                    if v['head']==adm['source']:assert b'1 passed'in nr and b'0 failed'in nr
                    assert v['native_bytes']>1_000_000;natives[label]=[v['native_sha256'],v['native_list_sha256'],len(tests),v['native_bytes']]
                if p+'tasks/epochs.tsv'in names:
                    assert p+'hardware.json'not in names;stats=collections.defaultdict(lambda:[0,0,0]);roles=[]
                    for line in z.read(p+'tasks/epochs.tsv').splitlines():
                        row=line.split()
                        if row[0]==b'C':
                            ep,_,_,i,en,run=map(int,row[1:]);assert i>=0 and en>=run>=0
                            for index,val in enumerate((i,en,run)):stats[ep][index]+=val
                        if row[0]==b'I'and row[-1]==b'exec':
                            ep,tg=map(int,row[1:3]);raw=z.read(p+'tasks/'+f'{ep:05}.nul');argv=raw.split(b'\0')
                            assert argv[-1]==b''and int(argv[0])==tg;exe=argv[3].decode();av=[v.decode()for v in argv[4:-1]]
                            tool='rustc' if exe.endswith('/sdk/bin/rustc')else 'cargo'if exe.endswith('/sdk/bin/cargo')else 'Wild'if exe.endswith('/wild-ld/ld.bfd')else None
                            if tool is None:continue
                            crate=av[av.index('--crate-name')+1]if '--crate-name'in av else None
                            link=any(a in ('-Zlink-only','-Zlink-only=yes')or i and av[i-1]=='-Z'and a in('link-only','link-only=yes')for i,a in enumerate(av))
                            roles.append((ep,tool,crate,link,sha(raw),tg))
                    for ep,tool,crate,link,h,tg in roles:
                        execution.append([tool,crate,link,h,tg,stats[ep]]);assert len([q for q in v['processes'] if(q['tool'],q['crate'],q['link_only'],q['argv_sha256'],q['thread_group'],q['epoch_count'])==(tool,crate,link,h,tg,stats[ep])])==1
                        if tool=='rustc'and crate and not link:actual.append(crate)
                    assert len(roles)==len(v['processes'])and collections.Counter(actual)==collections.Counter(['ron','insta']if arm=='parent'else['ron'])
            assert sorted(invalid)==['invalid','invalid-again']and counts['first-unchanged']==r[arm]['primary_first_unchanged']
            assert all(natives[x]==natives['empty-new']for x in ('edit','first-unchanged','second-unchanged','third-unchanged-observed','repaired'))
            assert all(counts[m+'-unchanged']==r[arm]['control'][m][1]and counts[m+'-second-unchanged']==r[arm]['control'][m][2]for m in ('check','build'))
            out['roles'][arm]=dict(costs=counts,full=sorted(actual),native=natives,invalid=invalid,census=execution,footprint=r[arm]['footprint'])
        return out
def main():
    d=Path(__file__).resolve().parent;p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,default=d);p.add_argument('--write',type=Path);args=p.parse_args();d=args.inputs
    plan=json.loads((d/'pricing.json').read_bytes());ex=json.loads((d/'expected.json').read_bytes());arts=json.loads((d/'artifacts.json').read_bytes())['artifacts']
    result={}
    for role in ('PC','CP'):
        a,=[v for v in arts if f'-{role}-'in v['name']];result[role]=reopen(d/(role+'.zip'),a,plan,ex)
    assert result['PC']['boot']!=result['CP']['boot'] and result['PC']['archive_set']==result['CP']['archive_set']
    hold={}
    for stage in ('check-unchanged','build-unchanged'):
        gains=[]
        for v in result.values():
            p=v['roles']['parent']['costs'][stage];c=v['roles']['candidate']['costs'][stage];gains.append(c-p>10_000_000 and c>p*1.05)
        hold[stage]=all(gains)
    output={'run':ex['run'],'blocks':result,'hold_gates':hold,'hold_broad':any(hold.values())}
    if args.write:args.write.write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print('independently reopened:',len(result),'boots;',sum(len(a['costs'])for b in result.values()for a in b['roles'].values()),'whole counters;',sum(len(a['invalid'])for b in result.values()for a in b['roles'].values()),'E0308 verdicts;',hold)
if __name__=='__main__':main()
