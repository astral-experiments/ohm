"""Reopen the retained full native products and each untraced endpoint, with Python and zstd."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'native-apple-276-developer-293-v2' / 'readback'))
from returned import macho_text, suite_verdicts
from study import digest, need
import reopen_cgu

ORIGINAL = '50303b31f31c79af497c2451c6bf943db0ac4cec95ed910a842ade12e5a0bd59'
POINTS = ('edit-plus-repeat', 'edit', 'repeat-1', 'repeat-2')


class Pack:
    def __init__(self):
        c = json.loads((HERE/'custody.json').read_bytes())
        packed = HERE/'native-outputs.tar.zst'
        with packed.open('rb') as f:
            need(hashlib.file_digest(f, 'sha256').hexdigest() == c['packet_sha256'] and packed.stat().st_size == c['packet_bytes'], 'changed compressed evidence')
        manifest = None
        self.blobs = {}
        with subprocess.Popen(['zstd', '-dcq', str(packed)], stdout=subprocess.PIPE) as child:
            with tarfile.open(fileobj=child.stdout, mode='r|') as tar:
                for entry in tar:
                    need(entry.isreg() and entry.size < 25 * 2**20, 'invalid pack entry')
                    data = tar.extractfile(entry).read()
                    if entry.name == 'manifest.json':
                        need(manifest is None and digest(data) == c['member_manifest_sha256'], 'changed original member manifest')
                        manifest = json.loads(data)
                    else:
                        key = digest(data)
                        need(entry.name == 'b/'+key and key not in self.blobs, 'foreign or duplicate content')
                        self.blobs[key] = data
            need(child.wait() == 0, 'zstd failed')
        self.rows = manifest['rows']
        original = manifest['raw_archive']
        need(original == c['raw_zip'] and original['id'] == 12993185613 and original['digest'] == 'sha256:'+ORIGINAL and original['size_in_bytes'] == 55408649 and original['workflow_run']['head_sha'] == '80a6e1bca9f57532884126a90a942269ef9bb530', 'wrong original Actions archive')
        need(len(self.rows) == c['selected_original_members'] == 1007 and {r[0] for r in self.rows.values()} == set(self.blobs), 'altered selection')
        need(all(len(self.blobs[r[0]]) == r[1] for r in self.rows.values()), 'changed decoded file sizes')

    def namelist(self): return self.rows.keys()
    def decode(self, name): return self.blobs[self.rows[name][0]]
    def read(self, name): return gzip.compress(self.decode(name), mtime=0) if name.endswith('.gz') else self.decode(name)
    def json(self, name): return json.loads(self.decode(name))


class Body:
    def __init__(self, data): self.data = data
    def read_bytes(self): return self.data


def typed(p, base, success):
    events = [json.loads(line) for line in p.decode(base+'/stdout.gz').splitlines()]
    need(events[-1] == {'reason':'build-finished','success':success}, 'wrong typed Cargo exit')
    artifacts = [r for r in events if r['reason'] == 'compiler-artifact']
    keys = [(r['package_id'], r['target']['name'], ','.join(r['target']['kind']), tuple(r['features']), json.dumps(r['profile'], sort_keys=True, separators=(',',':'))) for r in artifacts]
    need(len(set(keys)) == len(keys), 'duplicate Cargo unit')
    dirty = sorted(k for k, r in zip(keys,artifacts) if not r['fresh'])
    fp = {k:digest(json.dumps(v, sort_keys=True, separators=(',',':')).encode()) for k,v in [('dirty',dirty),('roster',sorted(keys))]}
    return fp, [r['message']['code']['code'] for r in events if r['reason']=='compiler-message' and r['message'].get('code')]


def verify():
    p = Pack()
    refs = p.json('ast-test-structural/empty-references.json')
    reg = p.json('ast-registration.json')
    need(reg['rust'] == {'P':'2035696c5316079f5b2e4373aee834839aac97e9','C':'444c0273a2e2bc0b161e988d43c882349bc2d7a6'} and reg['cargo']=='735e1528ed741015c57676dccf05dbdc0ff7bed1', 'different compiler or Cargo')
    providers = p.json('provider-matrix/terminal.json')
    need(providers['passed'] and providers['commands']==392 and not any(providers['wrong_or_image_mismatch'].values()), 'provider gate failed')
    result = p.json('ast-test-screen/result.json')
    need(result['valid'] and result['acquired'] and result['orders']==['PC','CP'], 'missing counterbalanced screen')
    reopen_cgu.packed = lambda z,n:z.decode(n)
    def native(z,h):
        b=z.decode('test-executables/'+h+'.macho.gz'); need(digest(b)==h,'changed full returned program'); return b
    reopen_cgu.program = native
    proofs = {d.rsplit('/',1)[0]:reopen_cgu.verify(p,d.rsplit('/',1)[0]) for d in p.rows if d.endswith('/cgu-proof.json')}
    scopes = [v['scope'] for v in proofs.values()]
    need(scopes.count('kernel-xcode-ld+rustc-recipe')==20 and scopes.count('saved-rustc-recipe')==16 and len(scopes)==36, 'missing direct and held native proofs')
    def check(d, role, proof, q):
        t = q['product']; raw=native(p,t['raw']); need(proof['raw']==t['raw'], 'wrong witnessed raw image')
        need(macho_text(Body(raw))=={'raw':t['raw'],'text':t['text']} and suite_verdicts(p.decode(d+'/test-suite.gz'),t['tests'])==t['verdicts'] and len(t['tests'])==(54 if q['state']=='new' else 53),'wrong real suite outputs')
        identity = {k:proof[k] for k in ('modules','output','same_path_image')}
        ref = refs[role][q['state']]; need({**{k:v for k,v in t.items() if k!='raw'},'debug_identity':identity}=={k:v for k,v in ref.items() if k!='raw'}, 'own-clean signed program or verdicts changed')
        return {**t,'debug_identity':identity}
    raw_pairs={point:[] for point in POINTS}
    for i,order in enumerate(result['orders'],1):
        arm={}
        for role in order:
            for seq,phases in [('empty-old',['clean']),('empty-new',['clean']),('actual',['cold','edit','repeat-1','repeat-2','invalid','repair'])]:
                known={}
                for phase in phases:
                    d=f'ast-test-structural/pair-{i:02}/{role}/{seq}/{phase}'; q=p.json(d+'/verified.json'); fp,codes=typed(p,d,phase!='invalid')
                    native_events=q['native']; full=native_events['full']; link_only=native_events['link_only']; lds=native_events['linkers']
                    if phase in ('repeat-1','repeat-2'): need(full==(['zmij'] if role=='P' else []) and link_only==['ruff_python_ast'] and not lds,'incorrect unchanged work')
                    if phase in ('edit','repair'): need('ruff_python_ast' in full and len(lds)==1 and lds[0]['stock'],'edit did not link with Xcode')
                    if phase=='invalid': need(codes==['E0425'] and not lds and q['state']=='invalid','incorrect invalid-source outcome'); continue
                    if d in proofs:
                        proof=p.json(d+'/cgu-proof.json'); known[proof['raw']]=proof
                    else:
                        proof=known[q['product']['raw']]; need(p.json(d+'/prior-test-link.json')=={'raw':proof['raw'],'observed_recipe':proof['recipe'],'observed_argv':proof['linker_argv']},'no earlier physical link of this returned binary')
                    check(d,role,proof,q)
            arm[role]={}
            for point in POINTS:
                base=f'ast-test-screen/pair-{i:02}/{point}/{role}'; obs=p.json(base+'/observed.json'); last=obs['verified_ending_phase']; d=base+'/'+last
                need(not ({'CI','TF_BUILD'} & p.json(base+'/developer-environment.json').keys()) and p.json(base+'/empty.json')=={'target_entries':0,'shared_entries':0},'wrong environment or stores')
                need(obs['purpose']==point and obs['role']==role and d+'/exec.json.gz' not in p.rows and len(p.json(base+'/timed-final-ast-cache.json')['generations'])==1,'clock tracing or wrong generation')
                clock=obs['cargo']; need(clock['ns']==clock['stop_ns']-clock['start_ns']>0,'wrong elapsed time')
                for phase in (['edit','repeat-1'] if point=='edit-plus-repeat' else [last]):
                    dst=base+'/'+phase; fp,codes=typed(p,dst,True); need(not codes and fp==p.json(dst+'/typed.json')['fingerprint'],'typed measured Cargo output differs')
                if point=='edit-plus-repeat':
                    combined=p.json(base+'/combined.json'); need(combined['exit']==0 and combined['clock']==clock and not combined['intermediate_native_reference'],'wrong contiguous two-command clock')
                q=p.json(d+'/verified.json'); need(obs['native']==check(d,role,p.json(d+'/cgu-proof.json'),q),'wrong final endpoint program or suite')
                arm[role][point]=clock['ns']
        for point in POINTS: raw_pairs[point].append([arm['P'][point],arm['C'][point]])
    for point,pairs in raw_pairs.items():
        ratios=[a/b for a,b in pairs]; row=result['wall'][point]; need(pairs==row['raw_PC'] and ratios==row['ratios_P_over_C'] and not all(v>2 for v in ratios), 'wrong raw times or gate')
        print(point, pairs, [round(v,4) for v in ratios])
    cf=p.json('ast-test-confirm/result.json'); need(result['selected_endpoint'] is None and not cf['required'] and not cf['acquired'] and result['counter_scope']=='unavailable-or-inconclusive','unexpected inference')
    print('No endpoint passed both 2× gates. Zero held-out pairs. No confidence interval or instruction result.')


if __name__=='__main__': verify()
