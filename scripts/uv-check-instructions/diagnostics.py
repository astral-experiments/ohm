import json


def normalize(diags):
    # Parallel linting may attach a once-per-lint note to one of several
    # diagnostics with the same lint. Compare the complete non-note output
    # and the once note itself for each target, with duplicate counts.
    messages, notes = [], []
    for raw in diags:
        event = json.loads(raw)
        msg = event['message']
        for c in list(msg['children']):
            if not c['spans'] and c['message'].startswith('requested on the command line with '):
                msg['children'].remove(c)
                note = '    = note: '+c['message']+'\n'
                msg['rendered'] = msg['rendered'].replace(note,'')
                notes.append(json.dumps((event['target'],msg['code'],c),sort_keys=True))
        messages.append(json.dumps(event,sort_keys=True))
    return sorted(messages),sorted(notes)
