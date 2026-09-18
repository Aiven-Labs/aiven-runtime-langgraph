"""In-memory run index for tests only; production always requires PostgreSQL."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from service import RunService
from workflow import build_graph
from settings import Settings

def config():
    return Settings('postgresql://unused', 'test-password-long-enough', 's'*32, 'k'*32, local=True)

class MemoryRuns(RunService):
    def __init__(self, cfg=None):
        self.cfg = cfg or config()
        self.saver = InMemorySaver()
        super().__init__(None, build_graph(self.saver, self.cfg))
        self.rows = {}

    @contextmanager
    def lock(self, run_id):
        yield

    def row(self, run_id):
        if str(run_id) not in self.rows:
            raise HTTPException(404, 'Run not found')
        return self.rows[str(run_id)]

    def list(self):
        return [dict(id=i, request=r['request'], created_at=r['created_at'].isoformat()) for i,r in self.rows.items()]

    def create(self, request):
        run_id = str(uuid4())
        self.rows[run_id] = dict(request=request, created_at=datetime.now(timezone.utc))
        return self.execute(run_id, 'continue')
