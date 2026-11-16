from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Job
from src.services.business import dump
def save_job(s,data,i=None):
 r=s.get(Job,i) if i else Job()
 if not r:raise HTTPException(404,'维保作业不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'作业编号重复')
 return dump(r)
