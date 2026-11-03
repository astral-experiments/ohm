"""Retain only externally owned Cargo package units between independently empty Ruff histories."""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from urllib.parse import urlsplit, unquote
import locked_git
import git_manifests
import tomllib


def need(cond, reason):
    if not cond:raise ValueError(reason)


def sha(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def events(path):
    return [json.loads(line)for line in (path/'stdout').read_bytes().splitlines()]


def record(path, obj):
    path.write_text(json.dumps(obj,sort_keys=True,indent=1)+'\n')


def parcel(state, source, home, lock, phases, physical=True):
    packages={(p['name'],p['version']):p['checksum'] for p in lock['package'] if p.get('source','').startswith('registry+')}
    roots={};units={};sources={};macro=None;registered=home/'registry/src'
    for phase,path in phases.items():
        rows=events(path);need(rows[-1]=={'reason':'build-finished','success':True},'bad seeding Cargo verdict')
        reg=[];local=[]
        for r in rows:
            if r['reason'] not in ('build-script-executed','compiler-artifact'):continue
            pid=r['package_id']
            if not locked_git.external(pid):
                need(pid.startswith('path+file://'),'foreign local dependency')
                url=urlsplit(pid.removeprefix('path+'))
                need(not url.netloc and Path(unquote(url.path)).is_relative_to(source),'foreign local source URL')
                if r['reason']=='compiler-artifact':
                    need(Path(r['target']['src_path']).is_relative_to(source) and Path(r['manifest_path']).is_relative_to(source),'unregistered local Cargo source')
                if r['reason']=='compiler-artifact':local.append([pid,r['target']['name'],r['target']['kind']])
                continue
            vcs=pid.startswith('git+')
            if vcs:name,version,revision=locked_git.owner(pid,lock)
            else:
                key=pid.rsplit('#',1)[1];name,version=key.rsplit('@',1)
                need((name,version)in packages and '#' not in name,'unlocked prefix package')
            if r['reason']=='compiler-artifact':
                manifest=Path(r['manifest_path'])
                if vcs:
                    git_manifests.verify(pid,manifest,home,revision,name,physical)
                    if physical:locked_git.root(home,manifest.parent,revision)
                else:need(manifest.name=='Cargo.toml' and manifest.parent.name==name+'-'+version and manifest.parent.parent.parent==registered,'wrong external source')
                sources[pid]=str(manifest.parent)
                parts=r['filenames'];reg.append([pid,r['target']['name'],r['target']['kind']])
                if name=='get-size-derive2' and r['target']['kind']==['proc-macro']:
                    so,=[Path(x)for x in parts if x.endswith('.so')]
                    need(macro in (None,so),'multiple get-size images');macro=so
            else:parts=[r['out_dir']]
            for filename in parts:
                file=Path(filename)
                need((not physical or file.exists()) and file.is_relative_to(state),'external artifact outside private history')
                pieces=file.relative_to(state).parts
                rx=r'^((?:build|target)/debug/build/(?:registries/|workspaces/[0-9a-f]{16}/)v2-[0-9a-f]{16}/([^/]+)/([0-9a-f]{16}))/out(?:/.*)?$'
                m=re.fullmatch(rx,'/'.join(pieces))
                need(m and m[2]==name,('unknown signed Cargo package layout',pid,pieces))
                path=m[1];need(roots.setdefault(path,pid)==pid,'two packages claim a unit')
        units[phase]={'external':sorted(reg),'local':sorted(local)}
    need(roots and macro and (not physical or macro.is_file()),'missing real external prefix')
    return roots,units,macro,sources


def census(state,roots,home):
    actual={};checked={}
    for name in sorted(roots):
        unit=state/name;need(unit.is_dir() and not unit.is_symlink(),'external unit lost: '+name)
        for directory,dirs,files in os.walk(unit,followlinks=False):
            for fname in sorted(dirs+files):
                f=Path(directory)/fname;key=f.relative_to(state).as_posix();it=f.lstat();mode=stat.S_IMODE(it.st_mode);ident=(it.st_dev,it.st_ino)
                if stat.S_ISDIR(it.st_mode):continue
                if stat.S_ISLNK(it.st_mode):
                    to=f.resolve(strict=True)
                    relative=to.relative_to(state).as_posix() if to.is_relative_to(state)else None
                    need(to.is_relative_to(home/'registry/src') or relative is not None and any(relative==leaf or relative.startswith(leaf+'/')for leaf in roots),'unregistered external symlink')
                    entry=['symlink',os.readlink(f)]
                else:
                    need(stat.S_ISREG(it.st_mode),('unsupported external member',key,mode))
                    if ident not in checked:checked[ident]=sha(f)
                    entry=['regular',it.st_size,checked[ident]]
                actual[key]=[mode,*ident,*entry]
    return actual


class Prefix:
    def __init__(self,state,source,home,work,lock,phases):
        self.state=state;self.home=home;self.work=work;self.lock=lock;work.mkdir()
        self.roots,self.units,self.macro,self.sources=parcel(state,source,home,lock,phases)
        record(work/'owners.json',self.roots);record(work/'registered-units.json',self.units)
        (work/'Cargo.lock').write_bytes((source/'Cargo.lock').read_bytes())
        self.locked={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in lock['package']if p.get('source','').startswith('registry+')}
        self.archives=self.archive_digest();need(all(self.archives.get(k)==v for k,v in self.locked.items()),'different initially locked external archive')
        record(work/'registry-archives.json',self.archives)
        self.source_fixed=self.source_digest()
        record(work/'source-packages.json',self.source_fixed)
        self.fixed=None;self.fresh('after-seed')
        self.fixed=census(state,self.roots,home);self.fixed_bytes=json.dumps(self.fixed,sort_keys=True,separators=(',',':')).encode()
        (work/'external-members.json.gz').write_bytes(gzip.compress(self.fixed_bytes,compresslevel=2,mtime=0))
        self.macro_sha=sha(self.macro);self.number=0
        record(work/'initialized.json',dict(objects=len(self.fixed),bytes=sum(x[4]for x in self.fixed.values() if x[3]=='regular'),root_count=len(self.roots),sha256=hashlib.sha256(self.fixed_bytes).hexdigest(),macro_path=str(self.macro),macro_sha256=self.macro_sha))
    def archive_digest(self):
        paths=list((self.home/'registry/cache').glob('*/*.crate'));table={f.name:sha(f) for f in paths}
        need(len(paths)==len(table),'duplicate registry input pathname')
        return table
    def source_digest(self):
        result={};git_trees={}
        for pid,dirname in self.sources.items():
            if pid.startswith('git+'):
                _,_,rev=locked_git.owner(pid,self.lock);src=locked_git.root(self.home,Path(dirname),rev)
                if src not in git_trees:git_trees[src]=locked_git.verify(src,rev)
                result[pid]=[str(Path(dirname).relative_to(src)),git_trees[src]];continue
            root=Path(dirname)
            h=hashlib.sha256();count=0
            for f in sorted(root.rglob('*')):
                if f.is_symlink():
                    need(f.resolve(strict=True).is_relative_to(root),'external source symlink outside its locked package')
                    val=['link',os.readlink(f)]
                elif f.is_dir():continue
                else:
                    st=f.stat();need(stat.S_ISREG(st.st_mode),'unrecognized registry source')
                    val=['file',stat.S_IMODE(st.st_mode),st.st_size,sha(f)]
                h.update(json.dumps([f.relative_to(root).as_posix(),*val],separators=(',',':')).encode()+b'\n');count+=1
            result[pid]=[count,h.hexdigest()]
        return result
    def verify(self,label):
        actual=census(self.state,self.roots,self.home)
        need(self.archive_digest()==self.archives and self.source_digest()==self.source_fixed,'registry archive/extracted input bytes changed after qualification')
        if actual!=self.fixed:
            bad={k:[self.fixed.get(k),actual.get(k)] for k in self.fixed.keys()|actual.keys() if self.fixed.get(k)!=actual.get(k)}
            record(self.work/(label+'-refusal.json'),bad);raise ValueError(('external package bytes, modes, inodes or links changed',label,list(bad)[:12]))
        record(self.work/(label+'-external-identity.json'),dict(files=len(self.fixed),sha256=hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest(),macro=sha(self.macro),source_census=sha(self.work/'source-packages.json'),registry_archives=sha(self.work/'registry-archives.json')))
    def fresh(self,label):
        park=self.state.parent/'ruf009-external-leaves-in-flight';need(not park.exists(),'an external unit transfer was interrupted');park.mkdir()
        for leaf in self.roots:
            f=self.state/leaf;to=park/leaf
            need(f.resolve()==f and f.is_dir(),'unqualified external package path')
            to.parent.mkdir(parents=True,exist_ok=True);f.rename(to)
        # All preserved paths reached here through a real Cargo registry package row.
        # Every other byte, including .ohm-check-graphs, loose aliases and all incremental products, is privately owned by this history.
        need(self.state.name=='state' and not self.state.is_symlink() and self.state.is_dir(),'different sacrificial state')
        shutil.rmtree(self.state);self.state.mkdir()
        for leaf in self.roots:
            dest=self.state/leaf;dest.parent.mkdir(parents=True,exist_ok=True);(park/leaf).rename(dest)
        need(all(p.is_dir() and not p.is_symlink()for p in park.rglob('*')),'unrestored prefix entry');shutil.rmtree(park)
        # Keep the original registry file inodes/mtimes (native receipts can refer to them).
        # Remove the previous Cargo databases and every other unqualified user cache.
        keep=self.state.parent/'ruf009-registry-inputs-in-flight';keep.mkdir()
        for kind in ('cache','index','src'):
            (self.home/'registry'/kind).rename(keep/kind)
        pinned=self.home/'git'
        need(pinned.is_dir()and not pinned.is_symlink(),'locked Git input cache missing')
        pinned.rename(keep/'git')
        config=self.home/'config.toml';has_config=config.is_file()
        if has_config:
            need(not config.is_symlink(),'unexpected Cargo config');config.rename(keep/'config.toml')
        need(self.home.is_dir() and not self.home.is_symlink(),'unsafe Cargo input directory')
        shutil.rmtree(self.home);(self.home/'registry').mkdir(parents=True)
        for kind in ('cache','index','src'):(keep/kind).rename(self.home/'registry'/kind)
        (keep/'git').rename(self.home/'git')
        if has_config:(keep/'config.toml').rename(self.home/'config.toml')
        keep.rmdir()
        if self.fixed is not None:self.verify(label)
    def cold(self,phase,path):
        rows=events(path);ext=[];local=[]
        for r in rows:
            if r.get('reason')!='compiler-artifact':continue
            external=locked_git.external(r['package_id'])
            need(r['fresh'] is external,('independent Ruff cold/registered external proof',r['package_id'],r['target']['name'],r['fresh']))
            (ext if external else local).append([r['package_id'],r['target']['name'],r['target']['kind']])
        need({'external':sorted(ext),'local':sorted(local)}==self.units[phase],'different cold graph')
        return dict(registered_external=len(ext),independent_local=len(local))
