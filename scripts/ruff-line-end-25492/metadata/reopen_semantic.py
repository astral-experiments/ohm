"""Verify the captured ordinary result against the registered full CLI without running rustc."""
from contextlib import contextmanager
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
from contact import NS
from ordinary_edges import native_roster
from summarize_reader import summarize

HOST='326c52a936b982d06dcff3797aa35f4db2bd17007f20ff6bf29b202dfcdf135f'
FULL='2500e9d894aff9bf31314ae4e03a7e37e81d36ed9210b6a832902b72e8193e73'

@contextmanager
def opened(path,size,sha):
    with open(path,'rb') as fp:
        fp.seek(0,2);assert fp.tell()==size;fp.seek(0)
        assert hashlib.file_digest(fp,'sha256').hexdigest()==sha;fp.seek(0)
        with zipfile.ZipFile(fp) as z:
            assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None;yield z

def native(full,host,case):
    b='host-read-set/'+case+'/'
    docs=json.loads(gzip.decompress(full.read(case+'/delivered.json.gz')))['artifacts']
    files={f['path']:f for doc in docs for f in doc['files']}
    ordinary=json.loads(host.read(b+'original.json'))
    history=json.loads(host.read(b+'history.json'))
    signed,=[r for r in json.loads(full.read(case+'/processes.json'))['compilers'] if r['crate']=='ruff_python_trivia' and 'extra-filename=-b6513ba17a4b84a6' in r['args']]
    # Only the host-specific SDK-identity path component differs in these real compiler arguments.
    argv=ordinary['argv'];assert len(argv)==len(signed['args'])
    diffs=[i for i,(a,c) in enumerate(zip(argv,signed['args'])) if a!=c]
    assert all(NS.sub('v2-<sdk>',argv[i])==NS.sub('v2-<sdk>',signed['args'][i]) for i in diffs)
    ordinary_ref,=history['matches']
    reference=history['full_arguments'][ordinary_ref]
    assert [NS.sub('v2-<sdk>',v) for v in reference]==[NS.sub('v2-<sdk>',v) for v in signed['args']]
    externs=[x for i,x in enumerate(signed['args']) if i and signed['args'][i-1]=='--extern']
    known={e.partition('=')[0]:files[e.partition('=')[2]]['sha256'] for e in externs if e.partition('=')[2] in files}
    assert known.get('ruff_source_file')==ordinary['provider_sha256']
    normal=json.loads(host.read(b+'native-normal.json'));replayed=json.loads(host.read(b+'native-replayed.json'))
    lib,=[f for path,f in files.items() if Path(path).name=='libruff_python_trivia-b6513ba17a4b84a6.rlib']
    metadata,=[f for path,f in files.items() if Path(path).name=='libruff_python_trivia-b6513ba17a4b84a6.rmeta']
    raw_outputs=history['product_ids']['ruff_python_trivia'];assert raw_outputs[Path(metadata['path']).name]==metadata['sha256']
    rosters=[native_roster(q['members']) for q in (lib,normal,replayed)]
    assert rosters[0]==rosters[1]==rosters[2]
    def member(which,name):
        value,=[(size,h) for n,size,h in which['members'] if n==name];return value
    metas=[member(q,'lib.rmeta') for q in (lib,normal,replayed)]
    assert metas[0]==metas[1]==metas[2]
    typed={k:host.read(b+k+'.txt').decode() for k in ('ruff_source_file-typed','ruff_python_trivia-typed','replayed-typed')}
    assert typed['ruff_source_file-typed']==json.loads((HERE.parent/'ordinary.json').read_bytes())['phases'][case]['typed_by_features']['no-features']
    assert typed['ruff_python_trivia-typed']==typed['replayed-typed']=='"> é\\r\\n>\\n> β\\r"\n"> A\\n> B"\n""\n'
    return {'full_pid':signed['pid'],'ordinary_pid':ordinary['pid'],'argc':len(argv),'literal_argv_differences_only_sdk_namespace':diffs,
            'physical_externs':known,'total_externs':len(externs),'objects_verified_order_and_names_and_bytes':len(rosters[0]),
            'object_roster_sha256':hashlib.sha256(json.dumps(rosters[0],separators=(',',':')).encode()).hexdigest(),'embedded_rmeta':[metas[0][0],metas[0][1]],'separate_rmeta_sha256':metadata['sha256'],
            'raw_rlib':[lib['sha256'],normal['rlib'],replayed['rlib']],'raw_link_metadata':[member(q,'lib.rmeta-link') for q in (lib,normal,replayed)],'typed':typed}

def read(full,host,repo):
    results,graphs,_=summarize(host,repo)
    external={case:native(full,host,case) for case in ('old','edit','clean')}
    return compose(results,graphs,external)

def compose(results,graphs,external):
    all_states=graphs['states'];roster=[]
    by_case={}
    for case,data in all_states.items():
        rows=data['observations']['ordinary']['direct_guard_reads'];by_case[case]={(r['kind'],r['key']):r for r in rows}
        assert len(by_case[case])==len(rows)
    for ident in sorted(set().union(*(set(r) for r in by_case.values()))):
        rows=[by_case[c].get(ident) for c in ('old','edit','clean')]
        roster.append([*ident,next((r['def_path'] for r in rows if r and r['def_path']),None),*[r['value'] if r else None for r in rows]])
    diffs={k:v for k,v in graphs['summaries'].items() if k.endswith('root_key_only') and k.startswith('ordinary_')}
    return dict(source_full=FULL,source_host=HOST,actual=results,full_crosscheck=external,cratewide_query_results=diffs,
                roster_columns=['kind','key','provider_item_if_same_DefPathHash','old','edited','independent_new'],roster=roster)

def main():
    if len(sys.argv)==4 and sys.argv[1]=='hosted':
        import tempfile
        import reopen
        spec=(41478876616,13159100988,13337356,HOST,'67f171f718fb1d769c355295fa500b43c643e3af','failure','ruff-line-end-25492-trivia-read-set','Record the seven-unit real host trivia reader')
        with tempfile.TemporaryDirectory() as tmp:
            paths=[reopen.download(Path(tmp),r) for r in (reopen.DIAG,spec)]
            verify(*paths,*sys.argv[2:])
        return
    verify(*sys.argv[1:])

def verify(full,host,repo,out):
    with opened(full,33709414,FULL) as z1,opened(host,13337356,HOST) as z2:result=read(z1,z2,repo)
    Path(out).write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n')
    print('unprofiled OLD/edited:',result['actual']['counts']['ordinary_old_edit'])
    print('unprofiled edited/clean:',result['actual']['counts']['ordinary_edit_clean'])
    print('verified full CLI and both narrow native object counts:',[r['objects_verified_order_and_names_and_bytes'] for r in result['full_crosscheck'].values()])
if __name__=='__main__':main()
