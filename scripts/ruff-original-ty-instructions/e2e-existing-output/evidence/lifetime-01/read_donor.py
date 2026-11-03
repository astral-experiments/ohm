"""Reopen affected native inputs, behavioral verdicts, and the first refused full SHA."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import bound_inputs
SHA='35ea2b2315f26ec8866ee8d29fbe8648739a69725cf7df99441f3a4af0d60928'
def sha(x):return hashlib.sha256(x).hexdigest()
def read(path):
    assert path.stat().st_size==2051118 and sha(path.read_bytes())==SHA
    with ZipFile(path)as z:
        assert z.testzip()is None
        reg=json.loads(z.read('registration.json'));assert reg['run']=='41702972179'and reg['head']=='716d21476dc6933ce6a69079fe027ac747bf11dc'
        refused=json.loads(z.read('refused.json'));assert refused['phase']=='native-repair' and refused['reason']=='complete source output differs from signed reference'
        tags={};native={};args={};env={};payload={}
        for t in ('old','edit','warm1','warm2','earlier','four','native-repair'):
            m=json.loads(z.read(t+'-donor.json'))if t!='native-repair'else refused['actual']
            inv=json.loads(gzip.decompress(z.read(t+'/inventory.json.gz')));assert len(inv['executables'])==102 and m['sha256']==inv['executables'][inv['binary']]['elf']['sha256']
            native[t]=inv['executables'][inv['binary']]['elf'];bytes_=gzip.decompress(z.read(t+'/link-actor.tsv.gz'));raw=bytes_.decode();co,argv=bound_inputs.receive(raw,False);args[t]=argv
            assert co['bytes']==m['bytes'] and co['inputs']==m['n']==409 and ('\nVERIFIED\n' in raw)
            env[t]={r[1]:r[2]for r in(line.split('\t')for line in raw.splitlines())if r[0]=='ENV'}
            used=[x.split('\t') for x in raw.splitlines()if x.startswith('USED\t')];payload[t]=[x[2:5] for x in used]
            selected=next(x for x in used if Path(x[-1]).name=='symbols.o')
            tags[t]={'input_recipe_before_environment':co['key'],'ordered_payload_root':m['ordered_payload_root'],'input_bytes':co['bytes'],'misses':co['denied_lookups'],'native_sha256':m['sha256'],'emitted_blake3':m['emitted'][3],'symbols_bytes':selected[2],'symbols_blake3':selected[3]}
        assert len({tags[t]['input_recipe_before_environment']for t in ('edit','warm1','warm2')})==1
        assert len({tags[t]['native_sha256']for t in ('edit','warm1','warm2','earlier')})==1 and tags['four']['native_sha256']!=tags['earlier']['native_sha256']
        four=json.loads(z.read('four-donor.json'));assert four['exit']==83 and len(four['mutation']['changed_offsets'])==4
        assert json.loads(z.read('malformed-donor.json'))['successful']is False
        failed=z.read('malformed/stderr')+z.read('malformed/stdout.jsonl');assert b'DELIBERATELY'in failed
        assert b'1 failed;'in z.read('withheld-old-fails/stdout') and b'1 passed;'in z.read('native-repair-verdict/stdout')
        repair_args=[i for i,(a,b)in enumerate(zip(args['warm2'],args['native-repair']))if a!=b]
        assert repair_args==[4,23,36,*range(37,176)]
        changed_sec=[a[0]for a,b in zip(native['warm2']['sections'],native['native-repair']['sections'])if a!=b];assert changed_sec==['.note.gnu.build-id']
        assert payload['warm2']==payload['native-repair']and tags['warm2']['native_sha256']!=tags['native-repair']['native_sha256']
        envdiff=[k for k in env['edit']if env['edit'][k]!=env['warm1'][k]];assert envdiff==['"COLLECT_GCC_OPTIONS"']
        return {'registration':reg,'source_actor':json.loads(z.read('actor.json')),'original_sha256':SHA,'tags':tags,'warm_changed_environment_names':envdiff,'warm_argv_differences':[4,23,36],'after_failed_link_argv_changes':repair_args,'after_failed_link_differing_recorded_sections':changed_sec,'after_failed_link_differing_ordered_native_operands':0,'first_refusal':refused['reason'],'different_symbol_offsets':four['mutation']['changed_offsets'],'four_byte_exit':83}
if __name__=='__main__':print(json.dumps(read(Path(sys.argv[1])),indent=2,sort_keys=True))
