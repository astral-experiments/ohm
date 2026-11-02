"""Derive the published per-visit table from the original pre/post Linux snapshots."""
from pathlib import Path

def short(resources):
    children=resources['delta']['children'];cpu=children['utime_us']+children['stime_us'];kernel=resources['delta']['kernel_scope'];after=resources['after'];paths=after['cgroup']['paths'];leaf=max(paths,key=lambda k:len(Path(k).parts),default=None);assert len({str(Path(x).parent) for x in paths})<=len(paths)
    def val(key,field):return kernel.get(key,{}).get('delta',{}).get(field)
    out={'user_us':children['utime_us'],'system_us':children['stime_us'],'total_cpu_us':cpu,'minor_faults':children['minflt'],'major_faults':children['majflt'],'block_in':children['inblock'],'block_out':children['oublock'],'voluntary_switches':children['nvcsw'],'involuntary_switches':children['nivcsw'],'maxrss_high_water_increment':children['maxrss'],'snapshot_gap_ns':resources['delta']['snapshot_gap_ns'],'deepest_visible_cgroup':leaf or '','cgroup_throttle_periods':val(str(leaf)+'/cpu.stat','nr_throttled'),'cgroup_throttled_us':val(str(leaf)+'/cpu.stat','throttled_usec'),'cgroup_cpu_usage_us':val(str(leaf)+'/cpu.stat','usage_usec')}
    for group,path in (('cgroup',str(leaf)+'/'),('host','host/')):
        for resource in ('cpu','io','memory'):
            for magnitude in ('some','full'):out[f'{group}_{resource}_{magnitude}_stall_us']=val(path+resource+'.pressure',magnitude+'_total_us')
    for which in ('idle','iowait','steal'):
        cpus=[val('host/cpu-times',f'cpu{n}/{which}_jiffies')for n in after['affinity']];out['selected_cpus_'+which+'_jiffies']=sum(cpus)if all(v is not None for v in cpus)else None
    out['cgroup_quota']=after['files'].get(str(leaf)+'/cpu.max',{}).get('raw','').strip();out['host_loadavg_before']=resources['before']['files']['host/loadavg'].get('raw','').strip();out['host_loadavg_after']=after['files']['host/loadavg'].get('raw','').strip()
    return out
