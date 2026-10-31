import json, os, pathlib, subprocess, sys
p=pathlib.Path(__file__).resolve().parent
d=p/sys.argv[1]
d.mkdir()
results={}
for case,rc in [('family',23),('thread',37),('duplicate',19),('abort',13),('signals',14),('long',0),('escape',125),('escape3',125)]:
    args=[str(p/'observe'),str(d/(case+'.tsv')),'--',str(p/'fixture'),case]
    if case=='family': args.append(str(p/'control-script'))
    if case=='long':
        (d/'relative-exe').symlink_to('/usr/bin/true')
        args=[str(p/'observe'),str(d/'long.tsv'),'--','/usr/bin/python3','-IB',str(p/'long_argv.py'),str(d)]
    try: q=subprocess.run(args,capture_output=True,timeout=15)
    except subprocess.TimeoutExpired as e:
        (d/(case+'.stderr')).write_bytes(e.stderr or b'')
        results[case]={'timeout':True}
    else:
        for name in ['stdout','stderr']:(d/(case+'.'+name)).write_bytes(getattr(q,name))
        results[case]={'status':q.returncode, 'expected':rc}
    print(case,results[case],flush=True)
(d/'run.json').write_text(json.dumps(results,indent=2)+'\n')
if any('status' not in x or x['status']!=x['expected'] for x in results.values()):sys.exit(1)
