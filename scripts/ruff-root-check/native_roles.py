"""Reconstruct the complete physical task roster from every successful kernel exec record."""
from pathlib import Path
import stat

from graph import need
import processes

SYSTEM_LINKERS={'ld','ld.lld','ld.bfd','ld.gold','wild','rust-lld','mold'}


def capture(events,proxy):
    paths={}
    for name in sorted({exe for _,exe,_ in events}|{str(proxy)}):
        p=Path(name)
        try:st=p.stat()
        except FileNotFoundError:paths[name]=None;continue
        need(stat.S_ISREG(st.st_mode),('executed non-file',name))
        paths[name]=[st.st_dev,st.st_ino]
    return paths


def read(events,paths,sdk,tools,wild_name,proxy,proxy_record):
    need(len(proxy_record['sha256'])==64 and set(paths)=={exe for _,exe,_ in events}|{str(proxy)} and
         paths[str(proxy)]==proxy_record['paths'][str(proxy)][:2] and all(paths[p]==ident[:2] for p,ident in proxy_record['paths'].items() if p in paths),
         'missing literal native executable or changed rustup proxy identity')
    ids={tuple(tools[rel][1:3]):role for rel,role in [('bin/rustc','rustc'),('bin/cargo','cargo'),(wild_name,'wild')]}
    need(len(ids)==3 and tuple(paths[str(proxy)]) not in ids,'ambiguous actual native tools')
    for rel in ('bin/rustc','bin/cargo',wild_name):
        path=str(sdk/rel)
        if path in paths:need(paths[path]==tools[rel][1:3],('declared SDK disagrees with executed path',rel))
    rows={n:[] for n in ('cargos','cargo_queries','rustcs','wild_processes','wild_queries','other_linkers')}
    for pid,exe,argv in events:
        role=ids.get(tuple(paths[exe] or ()));name=Path(exe).name
        row={'pid':pid,'exe':exe,'argv':argv}
        if name=='rustc' and '--crate-name' in argv and role!='rustc':need(paths[exe]==paths[str(proxy)],'foreign rustc executed')
        if role=='rustc' and '--crate-name' in argv and not any(a.startswith('--print') for a in argv):
            linked=any(a in ('link-only','ohm-link-only') or a.startswith(('link-only=','-Zlink-only')) for a in argv)
            rows['rustcs'].append(row|{'crate':argv[argv.index('--crate-name')+1],'mode':'link-only' if linked else 'full'})
        elif role=='wild':
            if '-o' in argv:rows['wild_processes'].append(row|{'output':argv[argv.index('-o')+1]})
            else:
                need(set(argv[1:]) and set(argv[1:])<={'-v','--version','--help','--print-output-format'},'unrecognized stock Wild invocation')
                rows['wild_queries'].append(row)
        elif role=='cargo':rows['cargo_queries' if argv[1:] in (['-V'],['--version'],['-Vv']) else 'cargos'].append(row)
        elif name in SYSTEM_LINKERS:
            kind,output=processes.other_link(exe,argv);rows['other_linkers'].append(row|{'kind':kind,'output':output})
    need(len(rows['cargos'])==1,'more or fewer than one actual Cargo')
    return rows|{'real_cargo':1,'wild':len(rows['wild_processes']),'successful_exec_count':len(events)}


def counts(rows):
    return {'full':sum(x['mode']=='full' for x in rows['rustcs']),'link_only':sum(x['mode']=='link-only' for x in rows['rustcs']),
            'wild':len(rows['wild_processes']),'images':rows['successful_exec_count']}
