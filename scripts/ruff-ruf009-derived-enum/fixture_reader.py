"""Exercise the dirty-row reader on the two factory's real, source-bound before/after output pairs."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from output_binding import need,reconcile


def read_fixture(original):
    reg=json.loads((HERE/'factory.json').read_bytes())
    expected=reg['receipts']
    with original.open('rb')as file:
        need(hashlib.file_digest(file,'sha256').hexdigest()==expected[3] and original.stat().st_size==expected[2],'wrong factory receipts')
    result={}
    with zipfile.ZipFile(original)as zipped:
        for role,label in [('P','parent'),('C','candidate')]:
            packed=zipped.read('scope-evidence-'+label+'.tar.gz')
            need(hashlib.sha256(packed).hexdigest()==reg['guard_archives'][role],'wrong native fixture')
            with tarfile.open(fileobj=io.BytesIO(packed),mode='r:gz')as tar:
                fixture=json.load(tar.extractfile('kernel-edit/readback.json'))
                accepted=json.load(tar.extractfile('accepted.json'))
                need(fixture==accepted['kernel']['edit'],'changed fixture')
                types={'dep':'lib','app':'bin'}
                typed=sorted((crate,types[crate])for crate in fixture['dirty'])
                real=sorted((crate,types[crate])for crate in fixture['kernel'])
                output=[]
                for stage in ('before','after'):
                    observed={}
                    for crate,pair in fixture[stage].items():
                        body={}
                        for k,info in pair.items():
                            physical=tar.extractfile(f'kernel-edit/{stage}/{crate}.{k}').read()
                            need(hashlib.sha256(physical).hexdigest()==info['sha256'] and len(physical)==info['size'],'unbound fixture bytes')
                            row=dict(info);row['bytes']=row.pop('size')
                            body['dep-info'if k=='d'else k]=row
                        observed[crate+'/'+types[crate]]=body
                    output.append(observed)
                missing=reconcile(typed,real,*output)
                need(missing==([] if role=='P' else [['app','bin']]),'wrong physical skips')
                def rejects(label, function):
                    try:function()
                    except ValueError:return label
                    raise ValueError('accepted '+label)
                refused=[rejects('missing actual producer',lambda:reconcile(typed,[],*output)),
                         rejects('extra physical compiler',lambda:reconcile(typed,[*real,('other','bin')],*output))]
                if role=='P':refused.append(rejects('same app bytes from a different inode',lambda:reconcile(typed,[('dep','lib')],*output)))
                else:
                    changed=deepcopy(output[1]);changed['app/bin']['dep-info']['ctime_ns']+=1
                    refused.extend([rejects('changed output time',lambda:reconcile(typed,real,output[0],changed)),
                                    rejects('missing prior app',lambda:reconcile(typed,real,{},output[1]))])
                result[role]=dict(nominal=typed,physical=real,missing=missing,refused=refused)
    return result


if __name__=='__main__':
    print(json.dumps(read_fixture(Path(sys.argv[1])),sort_keys=True,indent=1))
