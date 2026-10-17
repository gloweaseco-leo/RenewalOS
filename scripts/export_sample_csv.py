"""Export repeatable synthetic CSV examples with dates relative to execution day."""
import csv
import tempfile
from pathlib import Path
from renewalos.db import initialize,connect
from renewalos.demo import load_demo

out=Path(__file__).resolve().parent.parent/'samples'
fields={
 'learners': ['learner_id','family_id','guardian_alias','store_id','contact_consent'],
 'packages': ['package_id','learner_id','course_type','purchased_on','expires_on','purchased_sessions','remaining_sessions','price_cny'],
 'attendance': ['event_id','learner_id','session_date','status'],
 'renewals': ['renewal_id','learner_id','source_package_id','paid_on','amount_cny','status']}
with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'temp.sqlite'
    initialize(path)
    load_demo(path)
    with connect(path) as con:
        for table,columns in fields.items():
            rows=[dict(r) for r in con.execute(f'SELECT * FROM {table} ORDER BY 1')]
            with open(out/(table+'.csv'),'w',newline='',encoding='utf-8-sig') as fh:
                writer=csv.DictWriter(fh,fieldnames=columns)
                writer.writeheader()
                for r in rows:
                    if table=='learners':r['contact_consent']='yes' if r['contact_consent'] else 'no'
                    if table=='packages':r['price_cny']=f"{r.pop('price_cents')/100:.2f}"
                    if table=='renewals':r['amount_cny']=f"{r.pop('amount_cents')/100:.2f}"
                    writer.writerow(r)
print('Created: '+', '.join(str(out/(k+'.csv')) for k in fields))