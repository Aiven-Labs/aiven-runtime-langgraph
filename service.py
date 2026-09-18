"""Durable run index and explicit graph invocation; no background job queue."""
from contextlib import contextmanager
import logging
import threading
from uuid import UUID, uuid4
from fastapi import HTTPException
from langgraph.types import Command


class RunService:
    def __init__(self, pool, graph):
        self.pool, self.graph = pool, graph
        # Each execution needs a lock connection plus checkpoint connections.
        # Leave pool capacity for checkpoint writes and read-only API requests.
        self.capacity = threading.BoundedSemaphore(4)

    def setup(self):
        with self.pool.connection() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS starter_runs (
                id uuid PRIMARY KEY, request text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now())''')

    @staticmethod
    def config(run_id):
        return {'configurable': {'thread_id': str(run_id)}, 'recursion_limit': 20}

    @contextmanager
    def lock(self, run_id):
        # Session advisory locks are released even on process/connection loss.
        number = int.from_bytes(UUID(str(run_id)).bytes[:8], 'big', signed=True)
        if not self.capacity.acquire(blocking=False):
            raise HTTPException(503, 'The workspace is busy. Wait a moment, then refresh saved runs.')
        try:
            with self.pool.connection() as conn:
                if not conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (number,)).fetchone()['acquired']:
                    raise HTTPException(409, 'This run is already being processed. Refresh shortly.')
                try:
                    yield
                finally:
                    conn.execute('SELECT pg_advisory_unlock(%s)', (number,))
        finally:
            self.capacity.release()

    def row(self, run_id):
        with self.pool.connection() as conn:
            row = conn.execute('SELECT * FROM starter_runs WHERE id=%s', (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Run not found')
        return row

    def view(self, run_id):
        row = self.row(run_id)
        state = self.graph.get_state(self.config(run_id))
        values = dict(state.values or {})
        interrupted = any(task.interrupts for task in state.tasks)
        status = 'completed' if values.get('approved') else ('awaiting_review' if interrupted else 'needs_continue')
        return dict(id=str(run_id), request=row['request'], created_at=row['created_at'].isoformat(),
                    status=status, draft=values.get('draft', ''), revision=values.get('revision', 0),
                    mode=values.get('mode'), checkpoint=(state.config or {}).get('configurable', {}).get('checkpoint_id', ''))

    def list(self):
        with self.pool.connection() as conn:
            rows = conn.execute('SELECT id, request, created_at FROM starter_runs ORDER BY created_at DESC LIMIT 50').fetchall()
        return [dict(id=str(r['id']), request=r['request'], created_at=r['created_at'].isoformat()) for r in rows]

    def create(self, request):
        run_id = uuid4()
        with self.pool.connection() as conn:
            conn.execute('INSERT INTO starter_runs (id, request) VALUES (%s, %s)', (run_id, request))
        return self.execute(run_id, 'continue')

    def execute(self, run_id, action, feedback='', checkpoint=''):
        with self.lock(run_id):
            current = self.view(run_id)
            if current['status'] == 'completed':
                raise HTTPException(409, 'This run is already complete')
            if action == 'continue':
                if current['status'] == 'awaiting_review':
                    raise HTTPException(409, 'Submit a review decision to continue this run')
                initial = None if current['checkpoint'] else {'request': current['request'], 'revision': 0}
            else:
                if current['status'] != 'awaiting_review' or checkpoint != current['checkpoint']:
                    raise HTTPException(409, 'This review is out of date. Refresh the run.')
                initial = Command(resume={'action': action, 'feedback': feedback})
            try:
                self.graph.invoke(initial, self.config(run_id))
            except Exception as exc:
                # Do not expose provider payloads, connection strings or secrets.
                logging.getLogger(__name__).warning('Run %s paused after %s; explicit continuation required', run_id, type(exc).__name__)
                result = self.view(run_id)
                result['error'] = 'The step could not finish. Check service configuration, then continue the saved run.'
                return result
            return self.view(run_id)
