import os,json
import redis
from sqlalchemy import select,update
from fastapi import APIRouter,Depends,HTTPException,Response
from src.config.database import db
from src.models.entities import User,Job,MiningRun,AssociationRule,Kit,Audit,KittingPlan,KittingOccupancy,KittingPlanKit
from src.schemas.business import Login,JobInput,RunInput,KitInput,KitEdit,PlanTrial,PlanAction
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.jobs import save_job
from src.services import plans as plan_service
from src.controllers.business import ensure_run,ensure_rule,ensure_kit,ensure_plan
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/jobs')
def jobs(u=Depends(current),s=Depends(db)):
 occ={o.job_id:o.plan_id for o in s.query(KittingOccupancy).all()}
 return [{**dump(r),'occupied_by':occ.get(r.id)} for r in s.query(Job).order_by(Job.id).all()]
@router.post('/jobs')
def create_job(data:JobInput,u=Depends(editor),s=Depends(db)):
 r=save_job(s,data);audit(s,u,'录入作业 '+r['code']);return r
@router.put('/jobs/{i}')
def edit_job(i:int,data:JobInput,u=Depends(editor),s=Depends(db)):
 r=save_job(s,data,i);audit(s,u,'修订作业 '+str(i));return r
@router.get('/runs')
def runs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(MiningRun).order_by(MiningRun.id.desc()).all()]
@router.post('/runs')
def run(data:RunInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Job).order_by(Job.id).all() if data.equipment=='全部' or r.equipment==data.equipment]
 r=MiningRun(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('affinity:runs',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请恢复后新建挖掘';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交挖掘 '+str(r.id));return dump(r)
@router.get('/runs/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_run(s,i))
@router.get('/rules')
def rules(run_id:int,u=Depends(current),s=Depends(db)):
 ensure_run(s,run_id);return [dump(r) for r in s.query(AssociationRule).filter_by(run_id=run_id).order_by(AssociationRule.lift.desc()).all()]
@router.get('/runs/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_run(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功挖掘可以导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="parts-affinity-{i}.json"'})
@router.get('/kits')
def kits(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Kit).order_by(Kit.id.desc()).all()]
@router.post('/kits')
def kit(data:KitInput,u=Depends(editor),s=Depends(db)):
 rule=ensure_rule(s,data.rule_id)
 if ensure_run(s,rule.run_id).state!='done':raise HTTPException(409,'来源规则尚未完成')
 r=Kit(**data.model_dump(),parts=sorted(set(rule.antecedent+rule.consequent)),revision=1);s.add(r);s.commit();audit(s,u,'起草备件包 '+str(r.id));return dump(r)
@router.put('/kits/{i}')
def edit_kit(i:int,data:KitEdit,u=Depends(editor),s=Depends(db)):
 r=ensure_kit(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核备件包不可覆盖，需新建方案')
 r.name=data.name;r.note=data.note;r.revision=(r.revision or 0)+1;s.commit();audit(s,u,'修改备件包 '+str(i));return dump(r)
@router.post('/kits/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_kit(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核方案不可重复签核')
 r.status='approved';r.revision=(r.revision or 0)+1;s.commit();audit(s,u,'签核备件包 '+str(i));return dump(r)
@router.post('/kits/{i}/revoke')
def revoke(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_kit(s,i)
 if r.status!='approved':raise HTTPException(409,'仅已签核备件包可废止')
 in_use=~select(KittingPlanKit.id).join(KittingPlan,KittingPlan.id==KittingPlanKit.plan_id).where(KittingPlanKit.kit_id==i,KittingPlan.state=='active').exists()
 res=s.execute(update(Kit).where(Kit.id==i,Kit.status=='approved',in_use).values(status='revoked',revision=Kit.revision+1))
 if res.rowcount!=1:
  s.rollback()
  raise HTTPException(409,'备件包正被生效联备方案使用，请先取消相关方案')
 s.commit();audit(s,u,'废止备件包 '+str(i));return dump(s.get(Kit,i))
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
PLAN_SUMMARY=('solver','carry_limit','carried_parts','carried_count','covered','total','idle_total')
@router.post('/plans/trial')
def plan_trial(data:PlanTrial,u=Depends(editor),s=Depends(db)):
 p=plan_service.trial(s,u,data.name,data.job_ids,data.kit_ids or None,data.carry_limit);return dump(p)
@router.get('/plans')
def plan_list(u=Depends(current),s=Depends(db)):
 out=[]
 for p in s.query(KittingPlan).order_by(KittingPlan.id.desc()).all():
  d=dump(p);d['result']={k:p.result[k] for k in PLAN_SUMMARY if k in p.result};out.append(d)
 return out
@router.get('/plans/{i}')
def plan_detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_plan(s,i))
@router.post('/plans/{i}/confirm')
def plan_confirm(i:int,data:PlanAction,u=Depends(editor),s=Depends(db)):
 return dump(plan_service.confirm(s,u,i,data.idempotency_key))
@router.post('/plans/{i}/cancel')
def plan_cancel(i:int,data:PlanAction,u=Depends(editor),s=Depends(db)):
 return dump(plan_service.cancel(s,u,i,data.idempotency_key))
