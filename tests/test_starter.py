import base64
from pathlib import Path
import ssl
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import create_app
from settings import Settings
from service import RunService
from workflow import build_graph
from support import MemoryRuns, config


def test_busy_workspace_rejects_before_consuming_database_connections():
    service = RunService(None, None)
    for _ in range(4):
        service.capacity.acquire()
    with pytest.raises(HTTPException) as error:
        with service.lock(uuid4()):
            pytest.fail('A fifth execution must not acquire a connection')
    assert error.value.status_code == 503


def test_review_revision_and_resume_in_rebuilt_graph():
    runs = MemoryRuns()
    first = runs.create('Write a welcome note')
    assert first['status'] == 'awaiting_review' and first['revision'] == 1
    runs.graph = build_graph(runs.saver, runs.cfg)
    second = runs.execute(first['id'], 'revise', 'Keep it brief', first['checkpoint'])
    assert second['status'] == 'awaiting_review' and second['revision'] == 2
    assert 'Keep it brief' in second['draft']
    done = runs.execute(first['id'], 'approve', checkpoint=second['checkpoint'])
    assert done['status'] == 'completed'
    with pytest.raises(HTTPException) as error:
        runs.execute(first['id'], 'approve', checkpoint=second['checkpoint'])
    assert error.value.status_code == 409


def test_stale_review_cannot_approve_new_revision():
    runs = MemoryRuns()
    first = runs.create('Hello')
    runs.execute(first['id'], 'revise', 'Shorter', first['checkpoint'])
    with pytest.raises(HTTPException) as error:
        runs.execute(first['id'], 'approve', checkpoint=first['checkpoint'])
    assert error.value.status_code == 409


def test_failed_model_step_can_be_explicitly_continued(monkeypatch):
    cfg = config(); cfg.mode = 'openai-compatible'; cfg.model = 'example'; cfg.model_key = 'provider-secret'
    runs = MemoryRuns(cfg)
    def fail(*a, **kw):
        raise RuntimeError('provider-secret should never be returned')
    monkeypatch.setattr(httpx.Client, 'post', fail)
    failed = runs.create('Draft this')
    assert failed['status'] == 'needs_continue'
    assert 'provider-secret' not in str(failed)
    def success(*a, **kw):
        return httpx.Response(200, request=httpx.Request('POST','https://example.test'), json={'choices':[{'message':{'content':'A real-shaped response'}}]})
    monkeypatch.setattr(httpx.Client, 'post', success)
    resumed = runs.execute(failed['id'], 'continue')
    assert resumed['status'] == 'awaiting_review'
    assert resumed['draft'] == 'A real-shaped response'


def test_api_auth_csrf_validation_and_logout():
    cfg = config()
    with TestClient(create_app(cfg, MemoryRuns(cfg))) as client:
        assert client.get('/api/runs').status_code == 401
        assert client.post('/api/login', json={'password':'wrong'}).status_code == 401
        assert client.post('/api/login', json={'password':'é'*20}).status_code == 401
        login = client.post('/api/login', json={'password':cfg.password})
        assert login.status_code == 200 and 'httponly' in login.headers['set-cookie'].lower()
        token = client.get('/api/session').json()['csrf']
        assert client.post('/api/runs', json={'request':'Test'}).status_code == 403
        headers = {'X-CSRF-Token':token}
        assert client.post('/api/runs', json={'request':'   '}, headers=headers).status_code == 422
        run = client.post('/api/runs', json={'request':'Test'}, headers=headers).json()
        assert run['status'] == 'awaiting_review'
        assert client.post(f"/api/runs/{run['id']}/review", json={'action':'revise','feedback':'','checkpoint':run['checkpoint']}, headers=headers).status_code == 422
        assert client.post('/api/logout',headers=headers).status_code == 200
        assert client.get('/api/runs').status_code == 401
        assert client.get('/api/runs',headers={'Authorization':'Bearer '+cfg.api_key}).status_code == 200
        assert client.get('/api/runs',headers={'Authorization':'Bearer wrong'}).status_code == 401
        assert client.get(f'/api/runs/{uuid4()}',headers={'Authorization':'Bearer '+cfg.api_key}).status_code == 404


def test_login_rate_limit_and_secure_cookie():
    cfg = config(); cfg.local = False
    with TestClient(create_app(cfg, MemoryRuns(cfg)), base_url='https://testserver') as client:
        response = client.post('/api/login',json={'password':cfg.password})
        assert 'secure' in response.headers['set-cookie'].lower()
        for _ in range(9):
            client.post('/api/login',json={'password':'wrong'})
        assert client.post('/api/login',json={'password':'wrong'}).status_code == 429


def environment():
    return {'APP_PASSWORD':'p'*16,'SESSION_SECRET':'s'*32,'APP_API_KEY':'a'*32,
            'DATABASE_URL':'postgresql://u:p%40ss@db.example:5432/demo?sslmode=disable', 'LOCAL_DEVELOPMENT':'true'}


def test_settings_fail_closed(tmp_path):
    env = environment(); env['LOCAL_DEVELOPMENT']='false'
    with pytest.raises(ValueError): Settings.load(env,tmp_path/'ca.pem')
    env['LOCAL_DEVELOPMENT']='true';env['SESSION_SECRET']='short'
    with pytest.raises(ValueError): Settings.load(env)
    env = environment();env['MODEL_MODE']='openai-compatible'
    with pytest.raises(ValueError): Settings.load(env)


def test_settings_enforce_hostname_verification(tmp_path):
    env = environment();env['LOCAL_DEVELOPMENT']='false'
    cert = ssl.create_default_context().get_ca_certs(binary_form=True)[0]
    env['PG_CA_CERT_BASE64']=base64.b64encode(ssl.DER_cert_to_PEM_cert(cert).encode()).decode()
    cfg=Settings.load(env,tmp_path/'ca.pem')
    uri=urlsplit(cfg.database_url)
    assert uri.password=='p%40ss'
    assert parse_qs(uri.query)=={'sslmode':['verify-full'],'sslrootcert':[str(tmp_path/'ca.pem')]}
