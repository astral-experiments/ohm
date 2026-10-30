"""Project independently reopened native executions; preserve the source and archive bindings."""
import argparse
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from verify import packed,read,proof_native,prove_clocks

def structural(study,data):
    if study=='rust':
        groups={}
        for name,row in data['rows'].items():
            root,order,role,kind,step=name.split('/')
            assert root=='objc2-cli'
            groups.setdefault(order,{}).setdefault(role,{})[kind+'/'+step]=row
    else:groups=data['physical']
    proof_native(study,groups)
    return groups

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('topic',choices=['native','screen','confirmation'])
    p.add_argument('study',choices=['rust','cargo']);p.add_argument('source',type=Path);p.add_argument('out',type=Path)
    q=p.parse_args();data=read(q.source)
    if q.topic=='native':data=structural(q.study,data)
    else:prove_clocks(q.study,q.topic,data)
    b=packed(data)
    if q.out.exists():assert q.out.read_bytes()==b
    else:q.out.write_bytes(b)
if __name__=='__main__':main()
