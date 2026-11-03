"""Build the counted execv target and its full, unmodified argv separately."""
import json,os,shutil,subprocess

def command(counter,cost,argv,env):
    target=shutil.which(argv[0],path=env['PATH'])
    assert target and os.path.isabs(target)
    return [str(counter),str(cost),target,*argv]

def calibrate(counter,trial,env):
    output={}
    for name,code in [('true',0),('false',1)]:
        cost=trial/('counter-'+name+'.json')
        argv=command(counter,cost,[name],env)
        proc=subprocess.run(argv,env=env,capture_output=True,text=True)
        receipt=json.loads(cost.read_bytes())if cost.exists()else None
        ok=bool(proc.returncode==code and receipt is not None and receipt['instructions']>0 and receipt['running']>0 and receipt['enabled']<=1.01*receipt['running'] and receipt['status']==code<<8)
        output[name]={'argv':argv,'returncode':proc.returncode,'stderr':proc.stderr,'receipt':receipt,'matched':ok}
    return all(r['matched']for r in output.values()),output
