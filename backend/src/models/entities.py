from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Job(Base):
 __tablename__='jobs'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);equipment=Column(String(40));parts=Column(JSON);note=Column(Text,default='')
 revision=Column(Integer,default=1,nullable=False)
class MiningRun(Base):
 __tablename__='mining_runs'
 id=Column(Integer,primary_key=True);name=Column(String(100));equipment=Column(String(40));min_support=Column(Float);min_confidence=Column(Float);min_lift=Column(Float);state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class AssociationRule(Base):
 __tablename__='association_rules'
 id=Column(Integer,primary_key=True);run_id=Column(Integer,ForeignKey('mining_runs.id'));signature=Column(String(200));antecedent=Column(JSON);consequent=Column(JSON);support=Column(Float);confidence=Column(Float);lift=Column(Float);count=Column(Integer)
 __table_args__=(UniqueConstraint('run_id','signature'),)
class Kit(Base):
 __tablename__='kits'
 id=Column(Integer,primary_key=True);name=Column(String(100));rule_id=Column(Integer,ForeignKey('association_rules.id'));parts=Column(JSON);note=Column(Text);status=Column(String(20),default='draft')
 revision=Column(Integer,default=1,nullable=False)
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
class KittingPlan(Base):
 __tablename__='kitting_plans'
 id=Column(Integer,primary_key=True);name=Column(String(100));state=Column(String(20),default='draft')
 carry_limit=Column(Integer);basis=Column(JSON);fingerprint=Column(String(64));result=Column(JSON)
 confirm_key=Column(String(64),nullable=True);cancel_key=Column(String(64),nullable=True)
 version=Column(Integer,default=1,nullable=False);created_by=Column(String(100))
 created_at=Column(String(40));activated_at=Column(String(40),nullable=True);cancelled_at=Column(String(40),nullable=True)
class KittingOccupancy(Base):
 __tablename__='kitting_occupancy'
 id=Column(Integer,primary_key=True);plan_id=Column(Integer,ForeignKey('kitting_plans.id'));job_id=Column(Integer,ForeignKey('jobs.id'),unique=True,nullable=False);created_at=Column(String(40))
class KittingPlanKit(Base):
 __tablename__='kitting_plan_kits'
 id=Column(Integer,primary_key=True);plan_id=Column(Integer,ForeignKey('kitting_plans.id'));kit_id=Column(Integer,ForeignKey('kits.id'))
 __table_args__=(UniqueConstraint('plan_id','kit_id'),)
