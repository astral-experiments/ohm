"""Reopen complete marked graphs against both marked and original native output bytes."""
import json, os, shutil, sys, tempfile
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import common as c, solve
m=c.m

def reopen(out,work,reader):
    phases={'marked-A':'ordinary-A','marked-from-native-A-B':'ordinary-warm-B','marked-own-warm-B':'ordinary-warm-B','marked-cold-B':'ordinary-cold-B'}
    products={}
    for name in c.P['targets']:
        reports={};mapped={}
        for label,native in phases.items():
            marked=out/label
            proof=m.read(marked/'graph-proof.json')
            m.guard(proof['pass']and proof['evidence']['each_has_one_graph'],'no complete observer data '+label)
            info=proof['evidence']['selected'][name]
            occurrence,=info['trace']
            graph=marked/'traces'/name/occurrence['name']
            m.guard(graph.name==f"{info['pid']}-0.rdr.gz" and m.filesha(graph)==occurrence['gzip_sha256'],'wrong producing rustc process')
            seen={}
            for role in (label,native):
                path=out/role
                with ZipFile(path/'selected.zip')as z:
                    k,=[n for n in z.namelist() if Path(n).name.startswith('lib'+name+'-')]
                    size,h=m.read(path/'raw-inventory.json')[k];data=z.read(k)
                    m.guard(size==len(data) and h==m.digest(data),'original Cargo metadata checksum')
                    dest=work/(name+'-'+role+'.rmeta');dest.write_bytes(data)
                summary,values=solve.solve(graph,dest,reader,name)
                seen[role]=summary
                if role==label:mapped[label]=values
                else:m.guard(values==mapped[label],'unobserved emitted definitions/expansions do not support entire observed graph')
            reports[label]=seen
        a='marked-A';b='marked-from-native-A-B';own='marked-own-warm-B';cold='marked-cold-B'
        cmp=solve.compare(mapped[a],mapped[b])
        equality={k:all(mapped[k][v]==mapped[b][v]for v in solve.MODES)for k in (own,cold)}
        m.guard(all(equality.values()),'warm/cold identities or complete counterfactuals differ')
        common=mapped[a]['native'].keys()&mapped[b]['native'].keys()
        stabilized=sorted(k for k in common if mapped[a]['native'][k]!=mapped[b]['native'][k] and
                          mapped[a]['visibility_only'][k]==mapped[b]['visibility_only'][k])
        m.guard(len(stabilized)==cmp['projections']['visibility_only']['native_changes_made_stable'],'candidate set')
        products[name]={'all_graph_and_original_rmeta':reports,'A_to_first_B':cmp,'all_independent_B_projections_equal':equality,'actual_stabilized_local_keys':stabilized}
    return {'score':False,'classification':'Complete fixed-weight graph projection corroborated by each original native metadata product. These keyed counts do not establish cache demand, total crate hash, runtime or performance.','roles':products}

def main():
    ws,tmp,out=c.only_scope();reader=tmp/'root-20988-readers/uv-workflow-search/rdr_snapshot.py'
    m.guard(m.filesha(c.HERE/'solve.py')=='b5a9c642c39fb228a8703a2589074f508fc18edbf5d15be718145086458c72cd','solver changed')
    with tempfile.TemporaryDirectory(dir=tmp)as q:result=reopen(out,Path(q),reader)
    m.save(out/'observed-projection.json',result)
if __name__=='__main__':main()
