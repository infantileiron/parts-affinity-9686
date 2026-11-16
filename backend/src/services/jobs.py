from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Job,KittingOccupancy
from src.services.business import dump
def save_job(s,data,i=None):
 vals=data.model_dump()
 if not i:
  r=Job(**vals,revision=1);s.add(r)
  try:s.commit()
  except IntegrityError:s.rollback();raise HTTPException(409,'作业编号重复')
  return dump(r)
 # 条件更新：被生效联备方案占用的作业禁止修订；NOT EXISTS 子查询使检查与写入原子，
 # 与方案确认竞争时由行锁序列化，只保留一个一致版本。
 occupied=~select(KittingOccupancy.id).where(KittingOccupancy.job_id==i).exists()
 stmt=update(Job).where(Job.id==i,occupied).values(**vals,revision=Job.revision+1)
 try:res=s.execute(stmt);s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'作业编号重复')
 if res.rowcount!=1:
  s.rollback()
  if not s.get(Job,i):raise HTTPException(404,'维保作业不存在')
  held=s.query(KittingOccupancy).filter_by(job_id=i).first()
  raise HTTPException(409,f'作业已被生效联备方案 #{held.plan_id} 占用，请先取消该方案再修订')
 return dump(s.get(Job,i))
