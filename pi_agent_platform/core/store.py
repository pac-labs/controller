from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Iterable

from .models import AccessRequest, AgentContext, Event, Group, Session, Task, Runner, RunnerJob, RunnerJobStatus, User, UserWorkspace, now_utc
from .shared_storage import SharedStorage
from .config import ProxyRoute
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
            conn.execute('create table if not exists groups (id text primary key, payload text not null, updated_at text not null)')
            conn.execute('create table if not exists access_requests (id text primary key, user_id text not null, status text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_access_requests_status on access_requests(status, updated_at)')
            conn.execute('create table if not exists user_workspaces (id text primary key, owner_id text not null, owner_username text not null, name text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_user_workspaces_owner on user_workspaces(owner_id, updated_at)')
            conn.execute('create index if not exists idx_user_workspaces_owner_name on user_workspaces(owner_id, name)')
            conn.execute('create table if not exists agent_contexts (id text primary key, owner_id text not null, owner_username text not null, name text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_agent_contexts_owner on agent_contexts(owner_id, updated_at)')
            conn.execute('create index if not exists idx_agent_contexts_owner_name on agent_contexts(owner_id, name)')
            conn.execute('create table if not exists shared_storages (id text primary key, name text not null, payload text not null, updated_at text not null)')
            conn.execute('create index if not exists idx_shared_storages_name on shared_storages(name)')
            conn.execute('create table if not exists proxy_routes (id text primary key, payload text not null, updated_at text not null)')

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

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from sessions where id = ?', (session_id,))
        return cur.rowcount > 0

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
        with self._connect() as conn:
            rows = conn.execute(
                'select payload from events order by created_at desc limit ?',
                (max(limit * 8, 2000),),
            ).fetchall()
        items: list[Event] = []
        for row in rows:
            event = Event.model_validate_json(row['payload'])
            if event.type in excluded:
                continue
            items.append(event)
            if len(items) >= limit:
                break
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

    def add_group(self, group: Group) -> Group:
        group.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into groups(id, payload, updated_at) values (?, ?, ?)',
                (group.id, group.model_dump_json(), group.updated_at.isoformat()),
            )
        return group

    def get_group(self, group_id: str) -> Group | None:
        with self._connect() as conn:
            row = conn.execute('select payload from groups where id = ?', (group_id,)).fetchone()
        return Group.model_validate_json(row['payload']) if row else None

    def list_groups(self) -> list[Group]:
        with self._connect() as conn:
            rows = conn.execute('select payload from groups order by updated_at desc').fetchall()
        return [Group.model_validate_json(r['payload']) for r in rows]

    def delete_group(self, group_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from groups where id = ?', (group_id,))
        return cur.rowcount > 0

    def add_access_request(self, request: AccessRequest) -> AccessRequest:
        request.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into access_requests(id, user_id, status, payload, updated_at) values (?, ?, ?, ?, ?)',
                (request.id, request.user_id, request.status.value if hasattr(request.status, 'value') else str(request.status), request.model_dump_json(), request.updated_at.isoformat()),
            )
        return request

    def get_access_request(self, request_id: str) -> AccessRequest | None:
        with self._connect() as conn:
            row = conn.execute('select payload from access_requests where id = ?', (request_id,)).fetchone()
        return AccessRequest.model_validate_json(row['payload']) if row else None

    def list_access_requests(self, status: str | None = None) -> list[AccessRequest]:
        with self._connect() as conn:
            if status:
                rows = conn.execute('select payload from access_requests where status = ? order by updated_at desc', (status,)).fetchall()
            else:
                rows = conn.execute('select payload from access_requests order by updated_at desc').fetchall()
        return [AccessRequest.model_validate_json(r['payload']) for r in rows]

    def find_pending_access_request(self, user_id: str, resource_type: str, resource_id: str, access: str) -> AccessRequest | None:
        for item in self.list_access_requests(status='pending'):
            if item.user_id == user_id and item.resource_type == resource_type and item.resource_id == resource_id and item.access == access:
                return item
        return None

    def add_user_workspace(self, workspace: UserWorkspace) -> UserWorkspace:
        workspace.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into user_workspaces(id, owner_id, owner_username, name, payload, updated_at) values (?, ?, ?, ?, ?, ?)',
                (workspace.id, workspace.owner_id, workspace.owner_username, workspace.name, workspace.model_dump_json(), workspace.updated_at.isoformat()),
            )
        return workspace

    def get_user_workspace(self, workspace_id: str) -> UserWorkspace | None:
        with self._connect() as conn:
            row = conn.execute('select payload from user_workspaces where id = ?', (workspace_id,)).fetchone()
        return UserWorkspace.model_validate_json(row['payload']) if row else None

    def list_user_workspaces(self, owner_id: str | None = None) -> list[UserWorkspace]:
        with self._connect() as conn:
            if owner_id:
                rows = conn.execute('select payload from user_workspaces where owner_id = ? order by updated_at desc', (owner_id,)).fetchall()
            else:
                rows = conn.execute('select payload from user_workspaces order by updated_at desc').fetchall()
        return [UserWorkspace.model_validate_json(r['payload']) for r in rows]

    def find_user_workspace_by_name(self, owner_id: str, name: str) -> UserWorkspace | None:
        with self._connect() as conn:
            row = conn.execute('select payload from user_workspaces where owner_id = ? and name = ? order by updated_at desc limit 1', (owner_id, name)).fetchone()
        return UserWorkspace.model_validate_json(row['payload']) if row else None

    def delete_user_workspace(self, workspace_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from user_workspaces where id = ?', (workspace_id,))
        return cur.rowcount > 0

    def add_agent_context(self, context: AgentContext) -> AgentContext:
        context.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into agent_contexts(id, owner_id, owner_username, name, payload, updated_at) values (?, ?, ?, ?, ?, ?)',
                (context.id, context.owner_id, context.owner_username, context.name, context.model_dump_json(), context.updated_at.isoformat()),
            )
        return context

    def get_agent_context(self, context_id: str) -> AgentContext | None:
        with self._connect() as conn:
            row = conn.execute('select payload from agent_contexts where id = ?', (context_id,)).fetchone()
        return AgentContext.model_validate_json(row['payload']) if row else None

    def list_agent_contexts(self, owner_id: str | None = None) -> list[AgentContext]:
        with self._connect() as conn:
            if owner_id:
                rows = conn.execute('select payload from agent_contexts where owner_id = ? order by updated_at desc', (owner_id,)).fetchall()
            else:
                rows = conn.execute('select payload from agent_contexts order by updated_at desc').fetchall()
        return [AgentContext.model_validate_json(r['payload']) for r in rows]

    def find_agent_context_by_name(self, owner_id: str, name: str) -> AgentContext | None:
        with self._connect() as conn:
            row = conn.execute('select payload from agent_contexts where owner_id = ? and name = ? order by updated_at desc limit 1', (owner_id, name)).fetchone()
        return AgentContext.model_validate_json(row['payload']) if row else None

    def delete_agent_context(self, context_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from agent_contexts where id = ?', (context_id,))
        return cur.rowcount > 0

    def add_shared_storage(self, storage: SharedStorage) -> SharedStorage:
        storage.touch()
        with self._lock, self._connect() as conn:
            conn.execute(
                'insert or replace into shared_storages(id, name, payload, updated_at) values (?, ?, ?, ?)',
                (storage.id, storage.name, storage.model_dump_json(), storage.updated_at.isoformat()),
            )
        return storage

    def get_shared_storage(self, storage_id: str) -> SharedStorage | None:
        with self._connect() as conn:
            row = conn.execute('select payload from shared_storages where id = ?', (storage_id,)).fetchone()
        return SharedStorage.model_validate_json(row['payload']) if row else None

    def list_shared_storages(self) -> list[SharedStorage]:
        with self._connect() as conn:
            rows = conn.execute('select payload from shared_storages order by updated_at desc').fetchall()
        return [SharedStorage.model_validate_json(r['payload']) for r in rows]

    def delete_shared_storage(self, storage_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from shared_storages where id = ?', (storage_id,))
        return cur.rowcount > 0

    def list_proxy_routes(self) -> list[ProxyRoute]:
        with self._connect() as conn:
            rows = conn.execute('select payload from proxy_routes order by id asc').fetchall()
        return [ProxyRoute.model_validate_json(r['payload']) for r in rows]

    def get_proxy_route(self, route_id: str) -> ProxyRoute | None:
        with self._connect() as conn:
            row = conn.execute('select payload from proxy_routes where id = ?', (route_id,)).fetchone()
        return ProxyRoute.model_validate_json(row['payload']) if row else None

    def upsert_proxy_route(self, route: ProxyRoute, route_id: str) -> None:
        with self._lock, self._connect() as conn:
            now = now_utc().isoformat()
            conn.execute(
                'insert or replace into proxy_routes(id, payload, updated_at) values (?, ?, ?)',
                (route_id, route.model_dump_json(), now),
            )

    def delete_proxy_route(self, route_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute('delete from proxy_routes where id = ?', (route_id,))
        return cur.rowcount > 0


store = SQLiteStore()
