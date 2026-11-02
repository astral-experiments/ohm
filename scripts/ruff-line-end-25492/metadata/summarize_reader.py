"""Reopen ordinary graph edges and the changed enum from local record files or a complete ZIP."""
import gzip
import json
from pathlib import Path
import sys
import zipfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import enum_return
import ordinary_edges
import query_intervals
import query_values

class Directory:
    def __init__(self,path):self.path=Path(path)
    def read(self,key):return (self.path/key).read_bytes()
    def namelist(self):return [str(f.relative_to(self.path)) for f in self.path.rglob('*') if f.is_file()]

def summarize(z,repo):
    ref=json.loads((HERE/'full-host-operand.json').read_bytes())
    ordinary=ordinary_edges.extract(z);profiled=query_values.extract(z)
    enum=enum_return.read(z,str(repo));row={}
    for case,v in ordinary['states'].items():
        recorded=[e for e in ref['phase'][case]['externs'] if e['name']=='ruff_source_file'];assert len(recorded)==1
        obs=v['observations']['ordinary'];diag=v['observations']['profiled'];p=profiled['states'][case]
        assert v['provider']==p['physical']['provider']['sha256']
        times=None
        try:
            times=query_intervals.partition(z.read('host-read-set/'+case+'/profile.gz'),{r['index'] for r in diag['direct_guard_reads']},diag['target_index'])
        except (AssertionError,ValueError) as e:
            times={'refused':str(e)}
        row[case]={'source':v['source'],'normal_pid':v['regular_pid'],'diagnostic_pid':v['diagnostic_pid'],'physical_argv_sha':v['argv_sha'],
                   'provider_sha':v['provider'],'full_cli_provider_sha':recorded[0]['sha256'],'same_full_provider_bytes':recorded[0]['sha256']==v['provider'],
                   'original_files':{k:v[k] for k in ('ordinary_graph','profile_graph','query_profile')},'compiler':v['signed_rustc'],
                   'normal_graph':obs['graph'],'profiled_graph':diag['graph'],'native_members':v['native_members'],'native':v['native'],
                   'input_root':obs['guard_key'],'normal_reads':len(obs['direct_guard_reads']),'profiled_reads':len(diag['direct_guard_reads']),
                   'profile_direct_anchors':p['anchors'],'target_key':obs['target_key'],'target_value':obs['target_value'],'direct_parent':obs['direct_enum_callers'],
                   'query_time':times,'enum':enum[case]}
    counts={k:r['counts'] for k,r in ordinary['summaries'].items()}
    return dict(cases=row,counts=counts,ordinary_old_edit=ordinary['summaries']['ordinary_old_edit'],ordinary_edit_clean=ordinary['summaries']['ordinary_edit_clean'],
                native_hardware=ref['sampled_host_trivia_pids']),ordinary,profiled

def main(z,repo,out):
    summary,ordinary,profiled=summarize(z,repo)
    for n,data in [('ordinary',ordinary),('profiled',profiled)]:
        (out/(n+'-query-results.json.gz')).write_bytes(gzip.compress(json.dumps(data,sort_keys=True,separators=(',',':')).encode(),compresslevel=6,mtime=0))
    (out/'semantic-results.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    print('ordinary old/edit',summary['counts']['ordinary_old_edit'],'edit/clean',summary['counts']['ordinary_edit_clean'],flush=True)
    print('ordinary/profiled differences',[summary['counts'][c+'_ordinary_profile'] for c in ('old','edit','clean')],flush=True)
    print('original whole provider byte equal',{c:r['same_full_provider_bytes'] for c,r in summary['cases'].items()},flush=True)
    for r in summary['ordinary_old_edit']['differences']:
        print('changed ordinary edge',r['kind'],r['key'],r['status'],[x['def_path'] for x in r['left']],flush=True)
if __name__=='__main__':
    with zipfile.ZipFile(sys.argv[1]) as z:main(z,Path(sys.argv[2]),Path(sys.argv[3]))
