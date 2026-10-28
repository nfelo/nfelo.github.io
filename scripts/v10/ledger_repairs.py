"""Idempotent, evidence-linked corrections to inherited ledger rows.

Each match edit has an exact precondition. A subsequently corrected source
record is never overwritten just because an old repair mentions its ID.
"""
from collections import Counter
from datetime import date
import json
import hashlib
from pathlib import Path


def load_repairs():
    root=Path(__file__).parent
    raw=(root/'ledger_repairs.json').read_bytes()
    expected=json.loads((root/'engine/club_model.json').read_text()).get('input_repairs_sha256')
    if expected and hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('Reviewed input repair checksum differs')
    return json.loads(raw)


def apply_repairs(connection, payload=None):
    if payload is None:
        payload=load_repairs()
    fields=[x[0] for x in connection.execute('DESCRIBE matches').fetchall()]
    ids=[r['before']['match_id'] for r in payload['matches']]
    stored=connection.execute('SELECT * FROM matches WHERE match_id IN (SELECT unnest(?))',[ids]).fetchall() if ids else []
    actual_by_id={row[fields.index('match_id')]:{k:str(v) if isinstance(v,date) else v for k,v in zip(fields,row)} for row in stored}
    report={'applied':0,'already_applied':0,'changed_since_review':[], 'reasons':{}}
    reasons=Counter()
    for repair in payload['matches']:
        before,after=repair['before'],repair['after']
        actual=actual_by_id.get(before['match_id'])
        if actual is None or actual==after:
            report['already_applied']+=1
            continue
        if actual!=before:
            report['changed_since_review'].append(before['match_id'])
            continue
        if after is None:
            connection.execute('DELETE FROM matches WHERE match_id=?',[before['match_id']])
        else:
            changed=[k for k in fields if after[k]!=before[k]]
            if changed:
                connection.execute('UPDATE matches SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE match_id=?', [after[k] for k in changed]+[before['match_id']])
        report['applied']+=1;reasons[repair['reason']]+=1
    for repair in payload.get('clubs',[]):
        fields=list(repair['before'])
        row=connection.execute('SELECT '+','.join(fields)+' FROM clubs WHERE code=?',[repair['code']]).fetchone()
        if row is None:continue
        actual=dict(zip(fields,row))
        if actual==repair['after']:continue
        if actual!=repair['before']:
            report['changed_since_review'].append(repair['code']);continue
        connection.execute('UPDATE clubs SET '+','.join(k+'=?' for k in fields)+' WHERE code=?',[repair['after'][k] for k in fields]+[repair['code']])
        report['applied']+=1;reasons[repair['reason']]+=1
    report['reasons']=dict(reasons)
    return report


def held_records(connection):
    payload=load_repairs()
    clubs=dict(connection.execute('SELECT club,name FROM clubs').fetchall())
    rows=[]
    for repair in payload['matches']:
        if repair['after'] is not None or 'held for review' not in repair['reason']:continue
        row=dict(repair['before']);row['date']=row.pop('day')
        row['home']=clubs.get(row['home'],'Unresolved club');row['away']=clubs.get(row['away'],'Unresolved club')
        row['reason']=repair['reason'];row['source_ref']=repair['evidence']
        rows.append(row)
    return rows
