"""Recompute the six paired hardware observations from their archived raw controls."""
import csv
import hashlib
import json
import math
import statistics
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIGEST = '1eca42e1b919f127e77af130cc136bb23c38153fb6044213585982170da108e9'
COMMAND = ['cargo', '+ohm', 'test', '--no-run', '-p', 'ruff_db', '--lib', '--locked', '--offline', '-j2', '--message-format=json']

def check(ok, reason):
    if not ok:
        raise ValueError(reason)

def main():
    archive = HERE / 'ruff-27470-confirmation-raw-controls.tar.gz'
    check(hashlib.sha256(archive.read_bytes()).hexdigest() == DIGEST, 'raw archive changed')
    provenance = json.loads((HERE / 'provenance.json').read_bytes())
    with tarfile.open(archive) as tar, (HERE / 'pairs.tsv').open() as file:
        def get(key):
            return json.load(tar.extractfile(key))
        pairs = list(csv.DictReader(file, delimiter='\t'))
        confirmation = get('reader/confirmation.json')
        protocol = get('reader/hardware.json')
        api = get('github-provenance.json')
        replay = get('reopened.json')
        check(len(pairs) == 6 and sorted(confirmation['orders']) == ['CP']*3 + ['PC']*3 and replay['extra_local_execution'], 'missing fresh pair or independent native execution')
        check(api['run']['id'] == provenance['source_run'] == 41442143564 and api['run']['head_sha'] == provenance['source_head'] and api['run']['conclusion'] == 'success', 'incorrect source enrollment')
        boots = set()
        effects = {phase: [] for phase in ('old', 'edit', 'unchanged')}
        for slot, pair in enumerate(pairs, 1):
            root = f'raw-controls/slot-{slot}/'
            worker = get(root+'heldout-worker.json')
            entry = api['slots'][str(slot)]
            order = pair['order']
            index = protocol['order'].index(order)
            check(int(pair['slot']) == slot and order == confirmation['orders'][slot-1] == worker['order'] and worker['job'] == entry['job']['id'] and worker['runner_id'] == entry['job']['runner_id'] and worker['boot'] not in boots, 'incorrect independent worker')
            boots.add(worker['boot'])
            original = provenance['originals'][slot-1]
            check(original['artifact'] == entry['artifact']['id'] and 'sha256:'+original['original_sha256'] == entry['artifact']['digest'], 'original archive digest changed')
            for mode, copies in [('0',1), ('1',2), ('thread',2), ('exec',1)]:
                values = []
                for i in range(4):
                    event = get(root+f'meter/calibration/native-{mode}-{i}.json')
                    check(event['event_errno'] == 0 and event['enabled'] == event['running'] > 0, 'calibration counter failed')
                    values.append(event['instructions'])
                delta = statistics.mean(values[1:3])-statistics.mean([values[0],values[3]])
                check(abs(delta/(1400000*copies)-1) < .02, 'counter inheritance failed')
            prices = {}
            for role, label in [('P','parent'), ('C','candidate')]:
                folder = root+f'{index}-{role}/{role}-'
                old, new, clean = [get(folder+phase+'/objects.json') for phase in ('old','edit','clean')]
                check(len(old) == 216 and old.keys() == new.keys() == clean.keys(), 'different caller object roster')
                retained = 0
                for name, before in old.items():
                    after = new[name]
                    check(before['sha256'] == after['sha256'] == clean[name]['sha256'] and (before['identity'] == after['identity']) == after['same_pinned_donor'], 'incorrect pinned native donor')
                    retained += after['same_pinned_donor']
                check(retained == int(pair[label+'_old_objects']), 'wrong retained object count')
                prices[role] = {}
                for phase, field in [('old','cold'), ('edit','edit'), ('unchanged','unchanged')]:
                    stem = folder+phase+'/'
                    event, process, visit = [get(stem+key+'.json') for key in ('clock','process','visit')]
                    count = event['instructions']
                    check(event['event_errno'] == 0 and event['enabled'] == event['running'] > 0 and count == int(pair[label+'_'+field]) and process['argv'][2:] == COMMAND and process['exit'] == 0 and process['min_memory'] > 8<<30 and process['min_disk'] > 15<<30, 'wrong measured command or count')
                    want = protocol['expected']['old' if phase == 'old' else 'new']
                    check(visit['native']['elf'] == want['elf_sha256'] and visit['native']['oracle'] == want['oracle'] and visit['native']['test_count'] == 126, 'different test executable or renderer behavior')
                    prices[role][phase] = count
                errors = [x for x in map(json.loads,tar.extractfile(folder+'invalid/cargo.stdout')) if x.get('reason') == 'compiler-message' and x['message']['level'] == 'error' and x['message'].get('code')]
                check(len(errors)==1 and errors[0]['message']['code']['code']=='E0308' and errors[0]['target']['name']=='ruff_db' and get(folder+'invalid/process.json')['exit'] == 101, 'missing real type error')
                check(get(folder+'repair/visit.json')['native']['elf'] == get(folder+'clean/visit.json')['native']['elf'] == protocol['expected']['new']['elf_sha256'], 'stale repair')
                steady = get(folder+'unchanged/unchanged-physical.json')['protected']
                check(steady.keys() == set(old)|{':elf',':rlib'}, 'wrong unchanged inventory')
                for name, row in steady.items():
                    a,b,c = [row[k] for k in ('before','after','live_old')]
                    check(a[:3] == b[:3] == c[:3] and a[-1] == b[-1] == c[-1] and (a[3] != b[3]) == (name == ':elf'), 'unchanged physical identity differs')
            result = get(root+'hardware-confirmation.json')
            check(prices == result['price'] and len(result['old_object_gain']) == 38 and not result['old_object_loss'], 'paired output differs from raw counters or native controls')
            for phase in effects:
                effects[phase].append(1-prices['C'][phase]/prices['P'][phase])
        values = effects['edit']
        n = sum(x != 0 for x in values)
        tails = min(sum(x > 0 for x in values), sum(x < 0 for x in values))
        p = min(1, 2*sum(math.comb(n,i) for i in range(tails+1))/(2**n))
        median = statistics.median(values)
        check(median == replay['median_reduction'] and [min(values),max(values)] == replay['median_interval'] and p == replay['two_sided_exact_sign_p'], 'full independent replay disagrees')
        print(f'{median:.4%} fewer edited-command instructions. Exact 96.875% median interval [{min(values):.4%}, {max(values):.4%}]. Two-sided sign p = {p:.5f}.')
        print(f'Cold reduction {statistics.median(effects["old"]):.4%}. Unchanged reduction {statistics.median(effects["unchanged"]):.4%}.')

if __name__ == '__main__':
    main()
