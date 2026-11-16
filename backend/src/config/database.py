import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
url=os.environ['DATABASE_URL']
kwargs={'pool_pre_ping':True}
if url.startswith('sqlite'):
 kwargs['connect_args']={'check_same_thread':False,'timeout':15}
engine=create_engine(url,**kwargs)
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def db():
 with Session() as s: yield s
