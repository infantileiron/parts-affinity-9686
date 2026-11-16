from pydantic import BaseModel,Field,field_validator
from typing import Literal
from src.constants.enums import PARTS
class Login(BaseModel):email:str;password:str
class JobInput(BaseModel):
 code:str=Field(min_length=1,max_length=60)
 equipment:Literal['泵组','压缩机','风机']
 parts:list[str]=Field(min_length=1,max_length=30)
 note:str=Field(default='',max_length=1000)
 @field_validator('parts')
 @classmethod
 def validate_parts(cls,v):
  values=sorted(set(p.strip() for p in v))
  if any(p not in PARTS for p in values):raise ValueError('备件必须来自12项标准目录')
  return values
class RunInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 equipment:Literal['全部','泵组','压缩机','风机']='全部'
 min_support:float=Field(default=.15,gt=0,le=1,allow_inf_nan=False)
 min_confidence:float=Field(default=.6,gt=0,le=1,allow_inf_nan=False)
 min_lift:float=Field(default=1,ge=0,le=50,allow_inf_nan=False)
class KitInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 rule_id:int=Field(gt=0)
 note:str=Field(min_length=8,max_length=2000)
class KitEdit(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 note:str=Field(min_length=8,max_length=2000)
class RuleOutput(BaseModel):
 id:int;run_id:int;antecedent:list[str];consequent:list[str];support:float;confidence:float;lift:float;count:int
