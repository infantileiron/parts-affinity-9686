import random
from src.config.database import Base,engine,Session
from src.models.entities import User,Job
from src.constants.enums import PARTS,EQUIPMENT
from src.utils.security import hash_password
def seed():
 Base.metadata.create_all(engine);rng=random.Random(3108)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for i in range(180):
   code=f'YH-1115-{i+1:03}';equipment=EQUIPMENT[i%3]
   items=set(rng.sample(list(PARTS),rng.randint(1,3)))
   if i%3==0:items.update(['轴承','润滑脂'])
   if i%4==0:items.update(['密封圈','垫片'])
   if i%5==0:items.update(['滤芯','清洗剂'])
   if not s.query(Job).filter_by(code=code).first():s.add(Job(code=code,equipment=equipment,parts=sorted(items),note='远航维修策划组已核对作业用件，仅记录是否使用，不推算数量'))
  s.commit();print({'users':s.query(User).count(),'jobs':s.query(Job).count()})
if __name__=='__main__':seed()
