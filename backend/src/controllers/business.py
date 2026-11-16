from fastapi import HTTPException
from src.models.entities import MiningRun,AssociationRule,Kit
def ensure_run(s,i):
 r=s.get(MiningRun,i)
 if not r:raise HTTPException(404,'挖掘批次不存在')
 return r
def ensure_rule(s,i):
 r=s.get(AssociationRule,i)
 if not r:raise HTTPException(404,'来源规则不存在')
 return r
def ensure_kit(s,i):
 r=s.get(Kit,i)
 if not r:raise HTTPException(404,'备件包不存在')
 return r
