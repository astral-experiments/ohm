"""Validate and open a bounded semantic source packet in an actual full release Git checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE='d57fd1515986dccecdcece8da85e651bfb4b81f9'
TREE='f5bf03d73f71243fb88e34ecb0b155ef11e99a47'
ROLES={'ctfe_control':'dfcfe5fca8959d195ebc83b82288d6ba7bf8b73c','full_without_ctfe':'32433024be8a2b67fb6d1d13f8c981c8a3d3d660','full_with_ctfe':'ed34792bc273aa8c64e0dcf1b5cff77daa6967aa'}

def need(b,s):
    if not b:raise ValueError(s)
def sha(b):return hashlib.sha256(b).hexdigest()
def git(repo,*a,stream=None):return subprocess.check_output(['git','-C',repo,*a],input=stream,env={**os.environ,'GIT_NO_LAZY_FETCH':'1'})

def open_packet(repo,role,index,raw):
    need(role in ROLES and index['base']==BASE and index['base_tree']==TREE,'wrong semantic control/treatment');r=index['role_templates'][role];tip=r['template_commit'];p=r['packet'];need(r['tree']==ROLES[role] and r['parent']==BASE,'wrong preregistered role tree');need(len(raw)==p['bytes']<=1<<20 and sha(raw)==p['sha256'] and raw[:4]==b'PACK' and hashlib.sha1(raw[:-20]).digest()==raw[-20:],'packet material');need(git(repo,'rev-parse',BASE+'^{tree}').decode().strip()==TREE,'bad enrolled predecessor');need(git(repo,'rev-list','--objects','--no-object-names','--missing=error',BASE).count(b'\n')>60000,'incomplete shallow predecessor');out=git(repo,'index-pack','--strict','--stdin',stream=raw).decode().strip().split();need(len(out)==2 and out[0]=='pack' and out[1]==raw[-20:].hex(),'pack native index');idxdir=Path(git(repo,'rev-parse','--path-format=absolute','--git-path','objects/pack').decode().strip());idx=idxdir/f'pack-{out[1]}.idx';lines=git(repo,'verify-pack','-v',str(idx)).decode().splitlines();members={t[0]:t[1] for s in lines if len(t:=s.split())>=5 and len(t[0])==40};need(len(members)==len(p['objects'])==len(set(p['objects']))==int.from_bytes(raw[8:12],'big') and sorted(members)==p['objects'],'packet member set');need(sum(v=='commit'for v in members.values())==1 and members.get(tip)=='commit' and git(repo,'rev-parse',tip+'^',tip+'^{tree}').decode().splitlines()==[BASE,r['tree']],'not a single child of exact release');changes=git(repo,'diff-tree','--no-commit-id','--no-renames','-r','--name-only',BASE,tip).decode().splitlines();need(changes==r['changed_files'] and sorted(r['file_oids'])==changes,'changed file inventory');leaves={}
    for name in changes:
        row=git(repo,'ls-tree',tip,'--',name).decode().strip().split();need(len(row)==4 and row[1]=='blob' and row[3]==name and row[2]==r['file_oids'][name],f'leaf identity {name}');leaves[name]=sha(git(repo,'cat-file','blob',row[2]))
    all_objects=git(repo,'rev-list','--objects','--no-object-names','--missing=error',tip).decode().splitlines();need(len(all_objects)>60000,'incomplete child closure');return {'role':role,'source_commit':tip,'source_tree':r['tree'],'parent':BASE,'packet_sha256':sha(raw),'native_index_pack':out[1],'exact_packet_member_count':len(members),'complete_reachable_objects':len(all_objects),'all_reachable_sha256':sha(('\n'.join(sorted(all_objects))+'\n').encode()),'changed_files_sha256':leaves}

if __name__=='__main__':
    r,role,l,p=sys.argv[1:];print(json.dumps(open_packet(Path(r),role,json.loads(Path(l).read_bytes()),Path(p).read_bytes()),sort_keys=True))
