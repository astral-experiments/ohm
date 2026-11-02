"""Retain a separate restored first-edit process capture, independent of the two whole-command visits."""
from fractions import Fraction
from math import comb
from statistics import median
import os, subprocess
import core as c, history as h, scoped, products as prod
m=c.m
P=c.P

def visit(role, directory, role_qualification, sdks, state, expected, streams, products, output_controls, ready):
    target=directory/'scoped'
    if not ready:
        m.save(directory/'scoped-refused.json',{'reason':'host counters did not pass the enrolled calibration'})
        return {'qualified':False}
    try:
        scoped.measure(target,m.read(role_qualification/'typed-B/roster.json')['commands'],sdks[role]['runtime'])
    except (OSError,ValueError,AssertionError,RuntimeError,subprocess.SubprocessError) as error:
        m.save(directory/'scoped-refused.json',{'type':type(error).__name__,'reason':str(error)})
        c.guard(h.state('B')==state,'failed scoped capture disturbed source')
        return {'qualified':False}
    result=products(target)
    c.guard(h.state('B')==state and output_controls(target)==streams,'different command output on scoped first edit')
    c.guard(prod.compare(target/'same-seed-equivalence.json',expected,result,True),'scoped first-edit output differs from ordinary')
    m.save(target/'source.json',state)
    return {'qualified':True,'counts':m.read(target/'counts.json')}

def metric(values):
    rows=[Fraction(a,b) for a,b in values]
    above=sum(x>1 for x in rows);below=sum(x<1 for x in rows);n=above+below
    two_sided=min(Fraction(1),Fraction(2*sum(comb(n,k)for k in range(min(above,below)+1)),2**n)) if n else Fraction(1)
    h=[median(rows[:4]),median(rows[4:])]
    return {'paired_control_over_candidate':[float(x)for x in rows],'median_paired_factor':float(median(rows)),
            'hold_medians':[float(x)for x in h],'fewer_in_both_holds':all(x>1 for x in h),
            'both_hold_medians_at_least_twenty_percent_fewer':all(x>=Fraction(5,4)for x in h),
            'positive':above,'negative':below,'ties':len(rows)-n,'two_sided_paired_sign_p':float(two_sided),
            'observed_range':[float(min(rows)),float(max(rows))]}

def reduce(panel,raw,baseline,read_products,output_controls):
    all_pairs=[];failed=[]
    c.guard(len(raw)==8,'require every enrolled pair')
    for i,row in enumerate(raw):
        counts={}
        for role in c.ROLES:
            directory=panel/f'pair-{i}-{role}';qual=panel/f"hold-{row['hold']}-{role}";path=directory/'scoped'
            result=row['values'][role]['scoped']
            if not result['qualified']:
                c.guard((directory/'scoped-refused.json').is_file(),'missing scoped refusal')
                failed.append([i,role]);continue
            req=m.read(directory/'scoped-request.json')
            roster=m.read(qual/'typed-B/roster.json')
            selected={v[v.index('--crate-name')+1]:v for v in roster['commands']}
            c.guard(req['command']==c.CHECK and req['cwd']==str(m.SRC) and req['compiler_path']==str(m.RUSTC) and req['selectors']==selected and req['environment']==m.ENV,'changed process capture settings')
            y=scoped.read(path,req)
            c.guard(set(y)==set(P['edited_workspace_roster'])and y==result['counts']==m.read(path/'counts.json')and all(type(n)is int and n>0 for n in y.values()),'raw eight-PID PMUs or complete roster')
            expected,seal,streams=baseline[row['hold'],role];source=m.read(path/'source.json')
            c.guard(source['head']==P['A']and source['working_tree']==P['B_tree']and source['source']==P['B_file']and source['lock']==P['lock_sha256'] and result['checkpoint_sha256']==seal,'wrong first edit or complete parent')
            c.guard(read_products(path)==expected and m.read(path/'same-seed-equivalence.json')['passed'] and output_controls(path)==streams,'PMU source, diagnostics, metadata or output changed')
            counts[role]=y
        all_pairs.append({'pair':i,'hold':row['hold'],'order':row['order'],'user_instructions':counts})
    complete=not failed
    metrics={}
    if complete:
        ctrl,child=c.ROLES
        for label in [*P['edited_workspace_roster'],'sum_of_eight']:
            values=[]
            for row in all_pairs:
                arms=row['user_instructions']
                value=lambda role:sum(arms[role].values())if label=='sum_of_eight'else arms[role][label]
                values.append([value(ctrl),value(child)])
            metrics[label]=dict(metric(values),raw_control_candidate=values)
    return {'scope':'Eight true Cargo-dispatched rustc images and their threads, separately restored first edits; forked non-rustc children excluded','primary':'sum_of_eight','complete':complete,'refused':failed,'raw_pairs':all_pairs,'metrics':metrics}

def preregistered_tests(metrics):
    from domain_control import hypothesis
    return hypothesis(metrics)
