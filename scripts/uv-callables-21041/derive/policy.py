"""Score the prospectively published all-eight cumulative production endpoint."""
from fractions import Fraction
from math import comb
from statistics import median

ROSTER=('uv_cache', 'uv_client', 'uv_configuration', 'uv_distribution_types', 'uv_install_wheel', 'uv_metadata', 'uv_pypi_types', 'uv_torch')
def assess(metrics):
    actual={name:row['raw_control_candidate'] for name,row in metrics.items()}
    selected=set(actual)-{'sum_of_eight'}
    if selected!=set(ROSTER):
        raise ValueError('cumulative pricing requires all eight real rustc selectors')
    values=actual['sum_of_eight']
    if any(len(series)!=8 or any(len(row)!=2 or any(type(x)is not int or x<=0 for x in row)for row in series) for series in actual.values()):
        raise ValueError('requires sixteen strictly positive integer readings for every actual compiler and its sum')
    for i,row in enumerate(values):
        if any(row[k]!=sum(actual[c][i][k]for c in selected)for k in range(2)):
            raise ValueError('reported cumulative total differs from its eight original kernel counts')
    factor=[Fraction(a,b)for a,b in values];wins=sum(x>2 for x in factor);hold=[median(factor[:4]),median(factor[4:])]
    return {'primary':'sum_of_eight','strict_control_over_candidate_above':2,'raw_control_candidate':[list(x)for x in values],
            'raw_control_over_candidate':[str(x)for x in factor],'wins':wins,'holds':[str(x)for x in hold],
            'one_sided_exact_sign_p_ties_counted_against':float(Fraction(sum(comb(8,i)for i in range(wins,9)),2**8)),
            'qualified':wins==8 and all(x>2 for x in hold),'secondary':'all eight real individual rustcs, whole Cargo instructions and separate blocking wall'}
