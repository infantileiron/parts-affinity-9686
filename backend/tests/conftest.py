import os
import sys
import tempfile

os.environ.setdefault('DATABASE_URL', 'sqlite:///' + tempfile.mkdtemp(prefix='kitting_test_') + '/test.db')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('JWT_SECRET', 'kitting-test-secret')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.database import Base, Session, engine
from src.models.entities import Job, Kit, User
from src.utils.security import hash_password


@pytest.fixture(scope='session', autouse=True)
def _tables():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def clean(_tables):
    with Session() as s:
        for t in reversed(Base.metadata.sorted_tables):
            s.execute(t.delete())
        s.commit()


@pytest.fixture()
def client():
    app = FastAPI()
    from src.routes.api import router
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def make_user(role):
    with Session() as s:
        email = role + '@test.local'
        if not s.query(User).filter_by(email=email).first():
            s.add(User(email=email, role=role, password=hash_password('Test123!')))
            s.commit()


@pytest.fixture()
def tokens(client):
    out = {}
    for role in ('admin', 'analyst', 'viewer'):
        make_user(role)
        r = client.post('/auth/login', json={'email': role + '@test.local', 'password': 'Test123!'})
        assert r.status_code == 200, r.text
        out[role] = {'Authorization': 'Bearer ' + r.json()['token']}
    return out


def make_jobs(client, header, specs):
    """specs: [(code, parts)] -> {code: id}"""
    ids = {}
    for code, parts in specs:
        r = client.post('/jobs', json={'code': code, 'equipment': '泵组', 'parts': parts, 'note': ''}, headers=header)
        assert r.status_code == 200, r.text
        ids[code] = r.json()['id']
    return ids


def make_kit(name, parts, status='approved'):
    with Session() as s:
        k = Kit(name=name, rule_id=None, parts=sorted(parts), note='测试用包', status=status, revision=1)
        s.add(k)
        s.commit()
        return k.id


def get_job(job_id):
    with Session() as s:
        j = s.get(Job, job_id)
        return {'id': j.id, 'revision': j.revision, 'parts': j.parts}
