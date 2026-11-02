"""Run exactly one preassigned intact pilot pair per independent worker."""
import hashlib,json,os,subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import hardware as h

CONF=json.loads((HERE/'confirmation.json').read_bytes())

def slot_order():
    slot=int(os.environ['HELDOUT_SLOT']);need=h.need
    head=os.environ['REVIEWED_HEAD'];need(head==os.environ['GITHUB_SHA'] and os.environ['GITHUB_RUN_ATTEMPT']=='1','different confirmation revision/attempt');need(h.sha(HERE/'hardware.py')==CONF['pilot_driver_source_sha256'] and h.sha(HERE/'hardware.json')==CONF['pilot_hardware_protocol_sha256'],'original normal hardware driver differs')
    expected=int.from_bytes(hashlib.sha256(b'held-out confirmation first slot\0'+bytes.fromhex(CONF['scheduler_seed'])).digest(),'big')&1
    need(CONF['orders']==['CP'if (i+expected)%2 else'PC'for i in range(6)] and 1<=slot<=6,'different assigned orders');return slot,CONF['orders'][slot-1]

def register(slot,order):
    run=int(os.environ['GITHUB_RUN_ID']);base='repos/astral-experiments/ohm/actions/runs/'+str(run);api=lambda suffix:json.loads(subprocess.check_output(['gh','api',base+suffix]));state=api('');jobs=api('/attempts/1/jobs?per_page=100');name=f'Ruff library-test confirmation boot {slot}';own,=(j for j in jobs['jobs']if j['name']==name);boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();h.need(state['head_sha']==os.environ['REVIEWED_HEAD'] and state['event']=='workflow_dispatch' and state['run_attempt']==1 and own['runner_name']==os.environ['RUNNER_NAME'] and own['runner_id']>0 and boot!=CONF['pilot_boot'],'different or previously observed worker');h.save(h.checked.ROOT/'logs/heldout-worker.json',dict(run=run,job=own['id'],runner_id=own['runner_id'],runner=own['runner_name'],head=state['head_sha'],boot=boot,slot=slot,order=order,confirmation=h.sha(HERE/'confirmation.json')))

def finish(slot,order,index):
    prices={};kept={}
    for role in order:
        case=h.BASE/f'{index}-{role}';summary=json.loads((case/'summary.json').read_bytes());h.need(summary['role']==role and summary['order']==order and summary['caller_objects']==216,'different source/native history');kept[role]=set(summary['kept']);prices[role]={}
        for phase in h.PROTOCOL['scored']:
            event=json.loads((case/(role+'-'+phase)/'clock.json').read_bytes());h.need(not event['event_errno'] and event['instructions']>0 and event['enabled']==event['running']>0,'invalid counter window');prices[role][phase]=event['instructions']
    gains=sorted(kept['C']-kept['P']);losses=sorted(kept['P']-kept['C']);h.save(h.BASE/'hardware-confirmation.json',dict(slot=slot,order=order,primary=CONF['endpoint'],price=prices,reductions={p:1-prices['C'][p]/prices['P'][p]for p in h.PROTOCOL['scored']},old_object_gain=gains,old_object_loss=losses,worker=json.loads((h.checked.ROOT/'logs/heldout-worker.json').read_bytes()),confirmation=h.sha(HERE/'confirmation.json')))
    h.save(h.BASE/'terminal.json',dict(complete=True,slot=slot,order=order,confirmation=h.sha(HERE/'confirmation.json')))

if __name__=='__main__':
    h.checked.governance();slot,order=slot_order();index=h.PROTOCOL['order'].index(order);action=sys.argv[1]
    if action=='host':register(slot,order)
    elif action=='block':
        h.save(h.BASE/'confirmation-registration.json',CONF)
        for role in order:h.history(index,role)
    elif action=='finish':finish(slot,order,index)
    else:raise ValueError('unregistered action')
