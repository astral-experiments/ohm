"""Read ordinary child resources and its surrounding Linux cgroup and system counters outside the clock."""
from pathlib import Path
import os,re,resource,time

PS=("cpu","io","memory")
RUSAGE=("utime","stime","maxrss","minflt","majflt","inblock","oublock","nvcsw","nivcsw")
CG=("cpu.stat","cpu.max","cpu.pressure","io.stat","io.pressure","memory.pressure","memory.events")

def read(path):
    try:
        text=Path(path).read_text()
        if len(text)>400000:raise ValueError(("unexpected counter file size",str(path)))
        return {"raw":text}
    except OSError as exc:
        return {"unavailable_errno":exc.errno}

def unescape(text):
    return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),text)

def cgroups():
    source=Path('/proc/self/cgroup').read_text();mounts=Path('/proc/self/mountinfo').read_text().splitlines();groups=[];mount_rows=[]
    for line in mounts:
        left,right=line.split(' - ',1)
        if right.split()[0]!='cgroup2':continue
        cols=left.split();mount_root=Path(unescape(cols[3]));mounted=Path(unescape(cols[4]));mount_rows.append([str(mount_root),str(mounted)])
        for row in source.splitlines():
            typ,controllers,path=row.split(':',2)
            if typ!='0' or controllers:continue
            cgroup=Path(path)
            if not cgroup.is_relative_to(mount_root):continue
            leaf=mounted/cgroup.relative_to(mount_root)
            if '..'in leaf.parts or not leaf.is_dir():continue
            group=leaf
            while True:
                groups.append(str(group));
                if group==mounted:break
                group=group.parent
    return {'membership':source,'mounts':mount_rows,'paths':sorted(set(groups))}

def snapshot():
    start=time.monotonic_ns();tree=cgroups();usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    ru={k:getattr(usage,'ru_'+k)for k in RUSAGE};ru['utime_us']=round(ru.pop('utime')*1_000_000);ru['stime_us']=round(ru.pop('stime')*1_000_000)
    files={f'host/{n}.pressure':read('/proc/pressure/'+n)for n in PS}
    for group in tree['paths']:
        for n in CG:files[f'{group}/{n}']=read(Path(group)/n)
    allowed={'cpu',*(f'cpu{n}'for n in os.sched_getaffinity(0))};host_cpu=read('/proc/stat')
    if 'raw'in host_cpu:host_cpu['raw']='\n'.join(line for line in host_cpu['raw'].splitlines()if line.split()and line.split()[0]in allowed)+'\n'
    files['host/cpu-times']=host_cpu;files['host/loadavg']=read('/proc/loadavg');files['collector_and_waited_children/proc-io']=read('/proc/self/io')
    return dict(start_ns=start,end_ns=time.monotonic_ns(),affinity=sorted(os.sched_getaffinity(0)),cgroup=tree,children=ru,files=files)

def cumulative(key,raw):
    if key.endswith('cpu.max') or key=='host/loadavg':return {}
    if key=='host/cpu-times':
        labels=('user','nice','system','idle','iowait','irq','softirq','steal','guest','guest_nice');out={}
        for line in raw.splitlines():
            cpu,*vals=line.split();assert cpu=='cpu' or re.fullmatch(r'cpu[0-9]+',cpu);assert 7<=len(vals)<=len(labels)
            out.update({cpu+'/'+k+'_jiffies':int(v)for k,v in zip(labels,vals)})
        return out
    if key.endswith('.pressure'):
        out={}
        for line in raw.splitlines():
            category,*fields=line.split();values=dict(x.split('=',1) for x in fields);assert category in ('some','full') and len(values)==len(fields)and 'total'in values
            out[category+'_total_us']=int(values['total'])
        return out
    if key.endswith('io.stat'):
        out={}
        for line in raw.splitlines():
            device,*terms=line.split();assert re.fullmatch(r'\d+:\d+',device)
            for term in terms:
                label,value=term.split('=',1);out[device+'/'+label]=int(value)
        return out
    return {pieces[0].rstrip(':'):int(pieces[1])for line in raw.splitlines()if len(pieces:=line.split())==2}

def delta(a,b):
    assert a['cgroup']==b['cgroup']and a['affinity']==b['affinity']and a['files'].keys()==b['files'].keys()
    r={k:b['children'][k]-a['children'][k]for k in a['children']};assert all(n>=0 for n in r.values());files={}
    for k,x in a['files'].items():
        y=b['files'][k]
        if 'raw'not in x or 'raw'not in y:
            files[k]={'unavailable_before':x.get('unavailable_errno'),'unavailable_after':y.get('unavailable_errno')};continue
        v,w=cumulative(k,x['raw']),cumulative(k,y['raw']);common=v.keys()&w.keys()
        # A newly active or removed block device has no two physical endpoints. Never impute zero.
        files[k]={'delta':{n:w[n]-v[n]for n in sorted(common)},'appeared':sorted(w.keys()-v.keys()),'disappeared':sorted(v.keys()-w.keys())}
    return {'children':r,'kernel_scope':files,'snapshot_gap_ns':b['start_ns']-a['end_ns']}
