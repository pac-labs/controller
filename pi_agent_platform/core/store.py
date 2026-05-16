from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Iterable

from .models import Event, Session, Task, Runner, RunnerJob, RunnerJobStatus, User, now_utc
from .platform_home import pacp_path


class SQLiteStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else pacp_path('state.db')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute('pragma journal_mode=WAL')
            conn.execute('create table if not exists sessions (id text primary key, payload text not null, updated_at text not null)')
            conn.execute('create table if not exists tasks (id text primary key, session_id text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_tasks_session on tasks(session_id)')
            conn.execute('create table if not exists events (id text primary key, session_id text not null, task_id text, payload text not null, created_at text not null)')
            conn.execute('create table if not exists runners (id text primary key, payload text not null, updated_at text not null)')
            conn.execute('create table if not exists runner_jobs (id text primary key, runner_id text not null, status text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_runner_jobs_runner_status on runner_jobs(runner_id, status, updated_at)')
            conn.execute('create index if not exists idx_events_session_created on events(session_id, created_at)')
            conn.execute('create table if not exists users (id text primary key, payload text not null, updated_at text not null)')
            conn.execute('create table if not exists user_tokens (token text primary key, user_id text not null, expires_at text not null, created_at text not null)')
            conn.execute('create index if not exists idx_user_tokens_user on user_tokens(user_id, expires_at)')

    def add_session(self, session: Session) -> Session:
        session.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into sessions(id, payload, updated_at) values (?, ?, ?)',
                (session.id, session.model_dump_json(), session.updated_at.isoformat()),
            )
        return session

    def get_session(self, session_id: str) -> Session | None:
        with self._connect() as conn:
            row = conn.execute('select payload from sessions where id = ?', (session_id,)).fetchone()
        return Session.model_validate_json(row['payload']) if row else None

    def list_sessions(self) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute('select payload from sessions order by updated_at desc').fetchall()
        return [Session.model_validate_json(r['payload']) for r in rows]

    def add_task(self, task: Task) -> Task:
        task.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into tasks(id, session_id, payload, updated_at) values (?, ?, ?, ?)',
                (task.id, task.session_id, task.model_dump_json(), task.updated_at.isoformat()),
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as conn:
            row = conn.execute('select payload from tasks where id = ?', (task_id,)).fetchone()
        return Task.model_validate_json(row['payload']) if row else None

    def list_tasks(self, session_id: str | None = None) -> list[Task]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute('select payload from tasks where session_id = ? order by updated_at desc', (session_id,)).fetchall()
            else:
                rows = conn.execute('select payload from tasks order by updated_at desc').fetchall()
        return [Task.model_validate_json(r['payload']) for r in rows]

    def add_event(self, event: Event) -> Event:
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into events(id, session_id, task_id, payload, created_at) values (?, ?, ?, ?, ?)',
                (event.id, event.session_id, event.task_id, event.model_dump_json(), event.created_at.isoformat()),
            )
        return event

    def get_events(self, session_id: str, after_id: str | None = None, limit: int = 500, latest: bool = False) -> list[Event]:
        with self._connect() as conn:
            if after_id:
                marker = conn.execute('select created_at from events where id = ?', (after_id,)).fetchone()
                if marker:
                    rows = conn.execute(
                        'select payload from events where session_id = ? and created_at > ? order by created_at asc limit ?',
                        (session_id, marker['created_at'], limit),
                    ).fetchall()
                else:
                    order = 'desc' if latest else 'asc'
                    rows = conn.execute(f'select payload from events where session_id = ? order by created_at {order} limit ?', (session_id, limit)).fetchall()
            else:
                order = 'desc' if latest else 'asc'
                rows = conn.execute(f'select payload from events where session_id = ? order by created_at {order} limit ?', (session_id, limit)).fetchall()
        events = [Event.model_validate_json(r['payload']) for r in rows]
        if latest:
            events.reverse()
        return events


    def list_recent_events(self, limit: int = 200, exclude_types: set[str] | None = None) -> list[Event]:
        excluded = {str(item) for item in (exclude_types or set())}
        batch_size = max(limit * 4, 200)
        offset = 0
        items: list[Event] = []
        while len(items) < limit:
            with self._connect() as conn:
                rows = conn.execute(
                    'select payload from events order by created_at desc limit ? offset ?',
                    (batch_size, offset),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                event = Event.model_validate_json(row['payload'])
                if event.type in excluded:
                    continue
                items.append(event)
                if len(items) >= limit:
                    break
            if len(rows) < batch_size:
                break
            offset += batch_size
        return items

    def add_runner(self, runner: Runner) -> Runner:
        runner.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into runners(id, payload, updated_at) values (?, ?, ?)',
                (runner.id, runner.model_dump_json(), runner.updated_at.isoformat()),
            )
        return runner

    def get_runner(self, runner_id: str) -> Runner | None:
        with self._connect() as conn:
            row = conn.execute('select payload from runners where id = ?', (runner_id,)).fetchone()
        return Runner.model_validate_json(row['payload']) if row else None

    def list_runners(self) -> list[Runner]:
        with self._connect() as conn:
            rows = conn.execute('select payload from runners order by updated_at desc').fetchall()
        return [Runner.model_validate_json(r['payload']) for r in rows]

    def delete_runner(self, runner_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from runners where id = ?', (runner_id,))
        return cur.rowcount > 0

    def add_runner_job(self, job: RunnerJob) -> RunnerJob:
        job.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into runner_jobs(id, runner_id, status, payload, updated_at) values (?, ?, ?, ?, ?)',
                (job.id, job.runner_id, job.status.value if hasattr(job.status, 'value') else str(job.status), job.model_dump_json(), job.updated_at.isoformat()),
            )
        return job

    def get_runner_job(self, job_id: str) -> RunnerJob | None:
        with self._connect() as conn:
            row = conn.execute('select payload from runner_jobs where id = ?', (job_id,)).fetchone()
        return RunnerJob.model_validate_json(row['payload']) if row else None

    def list_runner_jobs(self, runner_id: str | None = None, status: str | None = None) -> list[RunnerJob]:
        with self._connect() as conn:
            if runner_id and status:
                rows = conn.execute('select payload from runner_jobs where runner_id = ? and status = ? order by updated_at desc', (runner_id, status)).fetchall()
            elif runner_id:
                rows = conn.execute('select payload from runner_jobs where runner_id = ? order by updated_at desc', (runner_id,)).fetchall()
            elif status:
                rows = conn.execute('select payload from runner_jobs where status = ? order by updated_at desc', (status,)).fetchall()
            else:
                rows = conn.execute('select payload from runner_jobs order by updated_at desc').fetchall()
        return [RunnerJob.model_validate_json(r['payload']) for r in rows]

    def claim_next_runner_job(self, runner_id: str) -> RunnerJob | None:
        with self._lock, self._connect() as conn:
            row = conn.execute('select id, payload from runner_jobs where runner_id = ? and status = ? order by updated_at asc limit 1', (runner_id, RunnerJobStatus.queued.value)).fetchone()
            if not row:
                return None
            job = RunnerJob.model_validate_json(row['payload'])
            job.status = RunnerJobStatus.claimed
            job.claimed_at = now_utc()
            job.touch()
            conn.execute('update runner_jobs set status = ?, payload = ?, updated_at = ? where id = ?', (job.status.value, job.model_dump_json(), job.updated_at.isoformat(), job.id))
            return job

    def add_user(self, user: User) -> User:
        user.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into users(id, payload, updated_at) values (?, ?, ?)',
                (user.id, user.model_dump_json(), user.updated_at.isoformat()),
            )
        return user

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute('select payload from users where id = ?', (user_id,)).fetchone()
        return User.model_validate_json(row['payload']) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute('select payload from users where id = ?', (username,)).fetchone()
        return User.model_validate_json(row['payload']) if row else None

    def list_users(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute('select payload from users order by updated_at desc').fetchall()
        return [User.model_validate_json(r['payload']) for r in rows]

    def delete_user(self, user_id: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute('delete from user_tokens where user_id = ?', (user_id,))
            cur = conn.execute('delete from users where id = ?', (user_id,))
        return cur.rowcount > 0

    def add_user_token(self, token: str, user_id: str, expires_at: str) -> None:
        now = now_utc()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into user_tokens(token, user_id, expires_at, created_at) values (?, ?, ?, ?)',
                (token, user_id, expires_at, now.isoformat()),
            )

    def get_user_by_token(self, token: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                'select user_id, expires_at from user_tokens where token = ?',
                (token,),
            ).fetchone()
        if not row:
            return None
        if row['expires_at'] < now_utc().isoformat():
            return None
        return self.get_user(row['user_id'])

    def list_user_tokens(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                'select ut.token, ut.user_id, u.payload as user_payload, ut.expires_at from user_tokens ut join users u on ut.user_id = u.id order by ut.expires_at asc'
            ).fetchall()
        items: list[dict[str, str]] = []
        for row in rows:
            user = User.model_validate_json(row['user_payload'])
            items.append({'token': row['token'], 'user_id': row['user_id'], 'username': user.username, 'expires_at': row['expires_at']})
        return items

    def delete_user_token(self, token: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute('delete from user_tokens where token = ?', (token,))


store = SQLiteStore()
