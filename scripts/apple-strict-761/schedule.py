"""Frozen independent Apple provider fault and migration histories."""
V='/dev/null/ohm-recheck-dependent-links'
P='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c';C='761ea115605c34f11a1cd29afd68812c1e1359dd'
BAD='qa_owned_external_missing_symbol'
def visit(label,state,rust=7):return (label,state,rust)
primary=(visit('signed-lower','lower'),visit('signed-unchanged-lower','lower'),visit('signed-poison-higher','higher'),
         visit('upgrade-higher','higher'),visit('strict-repeat-higher','higher'),visit('strict-malformed','malformed'),
         visit('strict-repair','higher'),visit('strict-missing','missing'),visit('strict-edit-repair','higher',11),
         visit('strict-repeat-edit','higher',11),visit('strict-invalid-source','higher',BAD),visit('strict-source-repair','lower',13),visit('strict-final-repeat','lower',13))
def poisoned(state):
    return (visit('signed-higher','higher'),visit('signed-poison-'+state,state),visit('upgrade-'+state,state),
            visit('strict-repair','higher'),visit('strict-repeat-repaired','higher'))
declared=(visit('signed-lower','lower'),visit('signed-declared-higher','higher'),visit('upgrade-higher','higher'),
          visit('strict-repeat-higher','higher'),visit('strict-declared-malformed','malformed'),visit('strict-repair','lower'))
transitive=(visit('signed-lower','lower'),visit('signed-poison-higher','higher'),visit('upgrade-higher','higher'),
            visit('strict-repeat-higher','higher'),visit('strict-malformed','malformed'),visit('strict-repair','lower'))
def checks():
    return [(kind,place,'unwatched',sequence) for place in ('direct','library') for kind,sequence in [('healthy',primary),('malformed',poisoned('malformed')),('missing',poisoned('missing'))]]+[
        ('declared','direct','declared',declared),('archive-owner','library','unwatched',transitive)]
