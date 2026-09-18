from collections import deque
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import secrets
import threading
import time
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Depends, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import BaseModel, Field, model_validator
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

from settings import Settings
from service import RunService
from workflow import build_graph

STATIC = Path(__file__).parent / 'static'
COOKIE = 'starter_session'


class Login(BaseModel):
    password: str = Field(max_length=1024)


class NewRun(BaseModel):
    request: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def nonblank(self):
        self.request = self.request.strip()
        if not self.request:
            raise ValueError('Enter a request')
        return self


class Review(BaseModel):
    action: Literal['approve', 'revise']
    feedback: str = Field(default='', max_length=2000)
    checkpoint: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def revision_feedback(self):
        self.feedback = self.feedback.strip()
        if self.action == 'revise' and not self.feedback:
            raise ValueError('Tell the workflow what to change')
        return self


def create_app(settings=None, service=None):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or Settings.load()
        app.state.settings = cfg
        app.state.signer = URLSafeTimedSerializer(cfg.session_secret, salt='langgraph-starter')
        if service is not None:
            app.state.runs = service
            yield
        else:
            # Keep setup synchronous and single-process before accepting requests.
            with ConnectionPool(cfg.database_url, min_size=1, max_size=10, timeout=10,
                                kwargs={'autocommit': True, 'prepare_threshold': 0, 'row_factory': dict_row}) as pool:
                pool.wait(timeout=60)
                saver = PostgresSaver(pool)
                saver.setup()
                app.state.runs = RunService(pool, build_graph(saver, cfg))
                app.state.runs.setup()
                yield

    app = FastAPI(title='LangGraph draft and review starter', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    attempts = deque()
    attempt_lock = threading.Lock()

    @app.middleware('http')
    async def response_headers(request, next_handler):
        response = await next_handler(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def authenticate(request: Request):
        cfg = request.app.state.settings
        header = request.headers.get('authorization', '')
        if header:
            if not hmac.compare_digest(header.encode(), ('Bearer ' + cfg.api_key).encode()):
                raise HTTPException(401, 'Invalid API key')
            return {'api': True}
        try:
            session = request.app.state.signer.loads(request.cookies.get(COOKIE, ''), max_age=28800)
        except BadSignature:
            raise HTTPException(401, 'Sign in to continue') from None
        if request.method not in ('GET', 'HEAD') and not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), session['csrf'].encode()):
            raise HTTPException(403, 'Refresh the page before trying again')
        return session

    @app.get('/health/live')
    def live():
        return {'status': 'alive'}

    @app.get('/health/ready')
    def ready(request: Request):
        if service is not None:
            return {'status': 'ready'}
        try:
            with request.app.state.runs.pool.connection() as conn:
                conn.execute('SELECT 1')
        except Exception:
            raise HTTPException(503, 'Database unavailable') from None
        return {'status': 'ready'}

    @app.post('/api/login')
    def login(body: Login, request: Request, response: Response):
        # A small shared demo has a global attempt budget, not a distributed limiter.
        with attempt_lock:
            now = time.monotonic()
            while attempts and attempts[0] < now - 60:
                attempts.popleft()
            if len(attempts) >= 10:
                raise HTTPException(429, 'Too many login attempts. Wait a minute.')
            attempts.append(now)
        if not hmac.compare_digest(body.password.encode(), request.app.state.settings.password.encode()):
            raise HTTPException(401, 'Incorrect password')
        token = request.app.state.signer.dumps({'csrf': secrets.token_urlsafe(32)})
        response.set_cookie(COOKIE, token, max_age=28800, httponly=True,
                            secure=not request.app.state.settings.local, samesite='strict')
        return {'ok': True}

    @app.get('/api/session')
    def session(request: Request, auth=Depends(authenticate)):
        cfg = request.app.state.settings
        return {'csrf': auth.get('csrf'), 'mode': cfg.mode, 'model': cfg.model if cfg.mode != 'mock' else None}

    @app.post('/api/logout')
    def logout(response: Response, auth=Depends(authenticate)):
        response.delete_cookie(COOKIE)
        return {'ok': True}

    @app.get('/api/runs')
    def runs(request: Request, auth=Depends(authenticate)):
        return request.app.state.runs.list()

    @app.post('/api/runs')
    def create(body: NewRun, request: Request, auth=Depends(authenticate)):
        return request.app.state.runs.create(body.request)

    @app.get('/api/runs/{run_id}')
    def get(run_id: UUID, request: Request, auth=Depends(authenticate)):
        return request.app.state.runs.view(run_id)

    @app.post('/api/runs/{run_id}/review')
    def review(run_id: UUID, body: Review, request: Request, auth=Depends(authenticate)):
        return request.app.state.runs.execute(run_id, body.action, body.feedback, body.checkpoint)

    @app.post('/api/runs/{run_id}/continue')
    def resume(run_id: UUID, request: Request, auth=Depends(authenticate)):
        return request.app.state.runs.execute(run_id, 'continue')

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


app = create_app()
