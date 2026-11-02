from collections import Counter
from pathlib import Path
import core as c
import history, cargo_log, units
m=c.m
def validate(path,rev,events,stderr,edited,material=True):
    plan=c.P;commands=cargo_log.running_rustcs(stderr,m.RUSTC);declared=units.unit_rows(events,m.SRC,m.TARGET,m.CARGO_HOME/'registry/src')
    m.save(path/'actual-units.json',declared)
    c.guard(declared['count']==plan['native_cargo_artifacts']==486 and declared['logical_sha256']==plan['native_complete_unit_sha256'] and units.workspace_shape(declared['workspace'])==plan['native_workspace_units'],'all real Cargo unit profiles/features/targets')
    active=[x for x in events if x['reason']=='compiler-artifact'and not x['fresh']]
    names=Counter(v['target']['name'].replace('-','_')for v in active)
    rust=Counter(v[v.index('--crate-name')+1]for v in commands);expected=Counter(plan['edited_workspace_roster']) if edited else Counter()
    rec={'commands':commands,'artifact_crates':dict(names),'completed':events[-1],'diagnostics':[x for x in events if x['reason']=='compiler-message'],'material':history.state(rev)}
    m.save(path/'roster.json',rec)
    c.guard(names==rust==expected,('actual dirty unit/command roster needs adjudication',names,rust,expected))
    return rec
def run(path,rev,edited):
    import run as primary
    so,se=primary.command(path,[*c.CHECK,'-vv','--message-format=json'],'typed')
    return validate(path,rev,cargo_log.cargo_messages(so),se,edited)
