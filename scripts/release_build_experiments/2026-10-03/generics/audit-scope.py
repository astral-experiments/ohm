#!/usr/bin/env python3
"""Check actual verbose rustc commands from the Cargo-policy cohort."""
import argparse,collections,json,pathlib,shlex
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
result=[]
for logfile in sorted(args.root.glob('**/policy/*/cold.log')):
    policy='-policy-' in logfile.parent.name
    record={'log':str(logfile),'policy':policy,'commands':[],'violations':[]}
    for line in logfile.read_text().splitlines():
        if 'Running `' not in line:continue
        raw=line.split('Running `',1)[1].removesuffix('`')
        try:tokens=shlex.split(raw)
        except ValueError:continue
        if not any(pathlib.Path(t).name=='rustc' for t in tokens) or '--crate-name' not in tokens:continue
        codes=[tokens[i+1] for i,t in enumerate(tokens[:-1]) if t=='-C']
        name=tokens[tokens.index('--crate-name')+1]
        kind=tokens[tokens.index('--crate-type')+1] if '--crate-type' in tokens else None
        source=next((token for token in tokens if token.endswith('.rs')),None)
        eligible=any(code in ['opt-level=2','opt-level=3'] for code in codes) and any(code in ['linker-plugin-lto','lto','lto=fat','lto=thin'] for code in codes)
        enabled='-Zshare-generics=yes' in tokens
        row={'crate':name,'crate_type':kind,'source':source,'codegen':codes,'lto_eligible':eligible,'shared_generics':enabled}
        record['commands'].append(row)
        if enabled != (policy and eligible):record['violations'].append(row)
    record['counts']=dict(collections.Counter('shared' if row['shared_generics'] else 'unshared' for row in record['commands']))
    result.append(record)
args.output.write_text(json.dumps(result,indent=2)+'\n')
for record in result:print(record['log'],record['counts'],'violations',len(record['violations']))
if any(record['violations'] for record in result):raise SystemExit(1)
