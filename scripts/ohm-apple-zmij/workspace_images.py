"""Store each full Cargo-returned image once, then tie it to its selected real linker."""
import collections
import gzip
import json
from pathlib import Path
import shutil

from cgu_inputs import witness
from study import digest,load,need,save
from verbs import macho_text

CHUNK=256*1024
MIN=8*2**30


class Image:
    def __init__(self,data):self.data=data
    def read_bytes(self):return self.data


def store(root, path):
    data=path.read_bytes();key=digest(data);store=root/'receipts/workspace-returned-images'
    record=store/'images'/(key+'.json')
    if not record.exists():
        need(shutil.disk_usage(root).free>MIN+2*len(data),'insufficient native evidence reserve')
        chunks=[]
        for n in range(0,len(data),CHUNK):
            fragment=data[n:n+CHUNK];h=digest(fragment)
            dst=store/'chunks'/h[:2]/(h+'.gz')
            if not dst.exists():
                dst.parent.mkdir(parents=True,exist_ok=True)
                with dst.open('xb') as f:f.write(gzip.compress(fragment,compresslevel=3,mtime=0))
            chunks.append([h,len(fragment)])
        shape=macho_text(Image(data));need(shape['raw']==key,'independent image reader disagrees')
        save(record,{'raw':key,'bytes':len(data),'text':shape['text'],'chunks':chunks})
    shape=load(record)
    need(shape['raw']==key and shape['bytes']==len(data),'foreign stored body')
    return data,shape


def outputs(native, events):
    certs=collections.defaultdict(list)
    by_argv=collections.defaultdict(list)
    for event in events:
        if Path(event['path']).name in ('ld','ld-prime','ld64','ld-classic'):
            a=event['argv'];by_argv[digest(json.dumps(a,separators=(',',':')).encode())].append(event)
    for row in native['linkers']:
        need(row['stock'],'foreign linker')
        a=row['argv'];h=digest(json.dumps(a,separators=(',',':')).encode())
        need(by_argv[h],'missing kernel linker execution')
        event=by_argv[h].pop(0)
        [p]=[v for k,v in zip(a,a[1:]) if k=='-o']
        certs[str(Path(p).resolve())].append({'output':p,'pid':event['pid'],'seq':event['seq'],
            'path':event['path'],'cdhash':event['cdhash'],'tool_sha256':row['sha'],'argv_sha256':h,'args':a})
    return certs


def bind(root, dest, path, unit, links, previous):
    data,image=store(root,path);key=image['raw']
    directory=dest/'workspace-image-proofs'/digest(json.dumps(unit,separators=(',',':')).encode())
    directory.mkdir(parents=True)
    if not links:
        prior=previous.get((str(path),key))
        if prior is None:
            entry={'link_origin':None,'error':'no previous physical linker for returned image in this installation'}
        else:
            entry={**prior,'current_link':False}
            save(directory/'prior.json',{'raw':key,'output':str(path),'own_link_origin':prior['link_origin']})
    elif len(links)!=1:
        entry={'link_origin':None,'error':'multiple physical links for the same typed output'}
    else:
        [link]=links;a=link['args'];source=link['output']
        need(Path(source).samefile(path) and [v for k,v in zip(a,a[1:]) if k=='-o']==[source],'mismatched real Xcode output')
        physical={k:v for k,v in link.items() if k!='args'}
        save(directory/'link.json',physical)
        entry={'link_origin':str(directory.relative_to(root/'receipts')),'current_link':True,'physical':physical}
        try:
            proof=witness(root,directory,data,source,linker=a)
            entry.update(own_image=proof['same_path_image'],cross_image=proof['cross_path_image'],
                         modules=digest(json.dumps(proof['modules'],sort_keys=True,separators=(',',':')).encode()),
                         module_count=len(proof['modules']),debug_paths=digest(json.dumps(proof['debug_paths'],separators=(',',':')).encode()),
                         output=source,recipe=proof['recipe'],nonce_objects=len(proof['nonce_objects']),error=None)
        except (RuntimeError, ValueError, OSError) as exc:
            # The exact image can still be compared by raw bytes. Eligible structural comparisons
            # will reject any unresolved difference and preserve this individual unit's evidence.
            entry['error']=str(exc)
            save(directory/'unsupported.json',{'cause':str(exc),'raw':key,'unit':unit})
        previous[str(path),key]=entry
    return {'raw':key,'length':len(data),'text':image['text'],**entry}


def compare(a,b,*,cross=False):
    if a['length']!=b['length'] or a['text']!=b['text']:
        return 'different-native-code-or-size'
    if a['link_origin'] is None or b['link_origin'] is None:return 'missing-own-real-link'
    if a['raw']==b['raw']:return 'exact'
    if a.get('error') or b.get('error'):return 'unresolved-native-difference'
    if a['modules']!=b['modules']:return 'different-compiled-module-bytes'
    if cross:
        return 'authenticated-cross-compiler' if (a['cross_image']==b['cross_image'] and a['debug_paths']==b['debug_paths']) else 'different-cross-compiler-native-image'
    return 'authenticated-local-names' if (a['own_image']==b['own_image'] and a['output']==b['output']) else 'different-same-compiler-native-image'
