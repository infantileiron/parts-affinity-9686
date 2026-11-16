import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import MiningRun,AssociationRule
from src.services.analysis import mine
r=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as recovery:
 for pending in recovery.query(MiningRun).filter(MiningRun.state.in_(['queued','running'])).all():pending.state='queued';r.rpush('affinity:runs',pending.id)
 recovery.commit()
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=r.blpop('affinity:runs',timeout=3)
  if not item:continue
  with Session() as s:
   row=s.get(MiningRun,int(item[1]))
   if not row or row.state!='queued':continue
   snapshot=row.result['snapshot'];row.state='running';s.commit()
   try:
    result=mine(snapshot,row.min_support,row.min_confidence,row.min_lift)
    s.query(AssociationRule).filter_by(run_id=row.id).delete()
    for rule in result['rules']:s.add(AssociationRule(run_id=row.id,**rule))
    row.result={**result,'snapshot':snapshot};row.state='done'
    Path('/artifacts/'+str(row.id)+'.json').write_text(json.dumps(row.result,ensure_ascii=False))
   except Exception as e:row.state='failed';row.error=str(e)
   s.commit()
 except Exception:logging.exception('worker');time.sleep(2)
