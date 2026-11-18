"""平台 schema 的唯一写入入口，升级前做 SQLite 一致性备份。"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import time

# 已发布的迁移只追加，不修改；v1 收拢既有三个初始化入口。
# 经开区快照首次导入时去掉了卫华的模型凭据列：凭据只从进程环境变量读取，
# 数据库从不保存模型密钥或其密文。本平台不接受卫华旧库直接升级。

MIGRATIONS = (
    (1, """
create table if not exists audit (
  id integer primary key autoincrement,
  ts real not null,
  app_id text not null,
  user_id text not null,
  action text not null,
  detail text not null
);
create table if not exists kv (
  app_id text not null,
  key text not null,
  value text not null,
  updated real not null,
  primary key (app_id, key)
);
create table if not exists v1_records (
 id text primary key, app text not null, latest integer not null
);
create table if not exists v1_versions (
 record_id text not null, version integer not null, document text not null,
 primary key(record_id,version)
);
create table if not exists v1_states (
 record_id text not null, version integer not null, status text not null,
 primary key(record_id,version)
);
create table if not exists v1_files (
 id text primary key, app text not null, project text not null,
 document text not null
);
create table if not exists v1_file_uses (
 file_id text not null, record_id text not null, version integer not null,
 primary key(file_id,record_id,version)
);
create table if not exists v1_refs (
 record_id text not null, version integer not null,
 source_app text not null, source_id text not null, source_version integer not null,
 file_id text
);
create index if not exists v1_refs_source on v1_refs(source_id,source_version);
create table if not exists v1_reviews (
 id text primary key, record_id text not null, version integer not null, document text not null
);
create table if not exists v1_decisions (
 id text primary key, review_id text not null, document text not null
);
create table if not exists v1_notifications (
 id text primary key, app text not null, recipient text not null, project text not null,
 document text not null
);
create table if not exists v1_notification_reads (
 notification_id text not null, user_id text not null,
 primary key(notification_id,user_id)
);
create table if not exists ai_provider(id text primary key, kind text not null,
            base_url text not null, models text not null, enabled integer not null);
          create table if not exists ai_route(capability text primary key, provider text not null,
            model text not null, fallback_provider text, fallback_model text);
          create table if not exists ai_quota(app_id text primary key, max_calls integer not null);
          create table if not exists ai_usage(id integer primary key, ts real not null, app_id text not null,
            capability text not null, provider text not null, status text not null, input_length integer not null,
            input_hash text not null);
"""),
    (2, """
create table if not exists app_control (
  app_id text primary key,
  enabled integer not null
);
"""),
    (3, """
create table if not exists external_sources (
 id text primary key, document text not null, secret blob not null
);
create table if not exists external_datasets (
 id text primary key, document text not null, snapshot text, synced_at real
);
create table if not exists external_syncs (
 id text primary key, dataset_id text not null, document text not null
);
"""),
    (4, """
create table if not exists v1_jobs (
 id text primary key, app text not null, submitter text not null,
 dedup_key text not null, request text not null, status text not null,
 document text not null, unique(app,submitter,dedup_key)
);
create index if not exists v1_jobs_status on v1_jobs(status);
create table if not exists v1_job_notifications (
 id text primary key, job_id text not null, attempt integer not null,
 document text not null, unique(job_id,attempt)
);
"""),
    (5, """
alter table ai_provider add column allow_outbound text;
"""),
    (6, """
create table if not exists app_registry (
 app_id text primary key, state text not null, audience_json text not null,
 version text not null, previous_version text, disabled_reason text,
 updated_at text not null, updated_by text not null, deployed_version text not null
);
create table if not exists app_runs (
 ts text not null, app_id text not null, user_id text, method text not null,
 path text not null, status integer not null, ms real not null, error text
);
create index if not exists app_runs_lookup on app_runs(app_id, ts);
"""),
    (7, """
create table if not exists kb_entries (
  id text primary key,
  document text not null
);
create table if not exists kb_versions (
  entry_id text not null,
  version integer not null,
  file_id text not null,
  document text not null,
  primary key(entry_id, version)
);
create index if not exists kb_versions_file on kb_versions(file_id);
"""),
    (8, """
create table users (
 id text primary key, username text not null unique, name text not null,
 password_hash text not null, status text not null, last_login text,
 failed_logins integer not null, locked_until real not null,
 demo integer not null, all_projects integer not null
);
create table companies (id text primary key, name text not null);
create table departments (id text primary key, name text not null, parent_id text);
create table positions (id text primary key, name text not null, department_id text);
create table user_departments (user_id text not null, department_id text not null,
 primary key(user_id, department_id));
create table user_positions (user_id text not null, position_id text not null,
 primary key(user_id, position_id));
create table roles (id text primary key, name text not null, builtin integer not null);
create table user_roles (user_id text not null, role_id text not null,
 primary key(user_id, role_id));
create table role_grants (role_id text not null, app_id text not null, action text not null,
 primary key(role_id, app_id, action));
create table projects (id text primary key, name text not null, company_id text not null,
 products text not null);
create table project_members (project_id text not null, user_id text not null,
 primary key(project_id, user_id));
create table settings (key text primary key, value text not null);
create table identity_apps (app_id text primary key);
"""),
    (9, """
alter table users add column session_gen integer;
"""),
    (10, """
create table if not exists v1_messages (
 id text primary key, app text not null, sender text not null, recipient text not null,
 idempotency_key text not null, request text not null, document text not null,
 read_at real, acknowledged_at real,
 unique(app,sender,idempotency_key,recipient)
);
create index if not exists v1_messages_recipient on v1_messages(recipient);
create index if not exists v1_messages_sender on v1_messages(app,sender);
"""),
    # CAP-01：飞书配置、群白名单、原消息、编辑修订、事件去重与断线缺口。
    # 已发布迁移只追加；并行任务若也占用 11，由 CEO 集成时重排编号并同步数据库版本。
    (11, """
create table if not exists feishu_config (
 id text primary key,
 app_id text not null,
 app_secret blob not null,
 verification_token blob,
 updated_at real not null,
 updated_by text not null
);
create table if not exists feishu_chats (
 chat_id text primary key,
 name text not null,
 purpose text not null,
 apps text not null,
 authorized_by text not null,
 authorized_at real not null,
 revoked_by text,
 revoked_at real
);
create table if not exists feishu_messages (
 message_id text primary key,
 app_id text not null,
 chat_id text not null,
 sender_id text not null,
 sender_type text not null,
 message_type text not null,
 content text not null,
 raw text not null,
 source text not null,
 message_create_time real not null,
 message_update_time real,
 collected_at real not null,
 state text not null,
 updated_at real not null
);
create index if not exists feishu_messages_chat on feishu_messages(chat_id, message_create_time);
create table if not exists feishu_message_revisions (
 message_id text not null,
 revision integer not null,
 content text not null,
 observed_at real not null,
 primary key(message_id, revision)
);
create table if not exists feishu_events (
 event_id text primary key,
 kind text not null,
 message_id text not null,
 chat_id text not null,
 received_at real not null
);
create table if not exists feishu_gaps (
 id text primary key,
 chat_id text not null,
 started_at real not null,
 ended_at real not null,
 reason text not null,
 recorded_by text not null,
 recorded_at real not null
);
create index if not exists feishu_gaps_chat on feishu_gaps(chat_id, started_at);
"""),
    # #67：按应用声明的主体字段授予跨项目只读范围；授权可撤销但不删除历史。
    (12, """
create table if not exists cross_project_grants (
 id text primary key, app_id text not null, subject_field text not null,
 subject_value text, principal_type text not null, principal_id text not null,
 created_by text not null, created_at real not null, revoked_by text, revoked_at real
);
create index if not exists cross_project_grants_lookup
 on cross_project_grants(app_id,subject_field,subject_value,principal_type,principal_id,revoked_at);
create table if not exists cross_project_subjects (
 app_id text not null, record_id text not null, version integer not null,
 subject_field text not null, subject_value text not null,
 primary key(app_id,record_id,version,subject_field)
);
create index if not exists cross_project_subjects_lookup
 on cross_project_subjects(app_id,subject_field,subject_value,version);
"""),
    (13, """
create table if not exists v1_schedule_bindings (
 app text not null, name text not null, project text not null,
 enabled integer not null, submitter text not null, enabled_at real not null,
 primary key(app,name,project)
);
create table if not exists v1_schedule_runs (
 app text not null, name text not null, project text not null, slot text not null,
 document text not null, primary key(app,name,project,slot)
);
create index if not exists v1_schedule_runs_recent on v1_schedule_runs(app,name,project,slot);
"""),
)

# 限制的是平台自己编写迁移的边界，防止误删、改列、DML 或给旧行添加新约束。
_IDENT = r'(?:[a-zA-Z_]\w*|"[^"]+")'
_CREATE = re.compile(rf'create\s+table\s+(?:if\s+not\s+exists\s+)?{_IDENT}\s*\(.+\)\s*;', re.I | re.S)
_INDEX = re.compile(rf'create\s+index\s+(?:if\s+not\s+exists\s+)?{_IDENT}\s+on\s+{_IDENT}\s*\(.+\)\s*;', re.I | re.S)
_ADD = re.compile(rf'alter\s+table\s+{_IDENT}\s+add\s+(?:column\s+)?{_IDENT}\s+(?:text|integer|real|blob|numeric)(?:\s+null)?\s*;', re.I)


def statements(script: str, *, version: int = 0) -> list[str]:
    out, buffer = [], ''
    for ch in script:
        buffer += ch
        if ch == ';' and sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if not any(pattern.fullmatch(statement) for pattern in (_CREATE, _INDEX, _ADD)):
                raise ValueError('迁移只允许新增表、普通索引或无默认值的可空列')
            out.append(statement)
            buffer = ''
    if buffer.strip():
        raise ValueError('迁移 SQL 未以完整分号结束')
    return out


def _backup(db, path):
    with closing(sqlite3.connect(path)) as backup:
        db.backup(backup)


def migrate(db: sqlite3.Connection, data_dir: Path) -> None:
    current = 0
    try:
        if db.execute("select 1 from sqlite_master where type='table' and name='schema_versions'").fetchone():
            versions = [row[0] for row in db.execute('select version from schema_versions order by version')]
            current = max(versions, default=0)
            if versions != list(range(1, current + 1)):
                raise ValueError('schema 版本记录不连续')
        if [version for version, _ in MIGRATIONS] != list(range(1, len(MIGRATIONS) + 1)):
            raise ValueError('迁移必须按版本连续追加')
        if current > len(MIGRATIONS):
            raise ValueError('数据库来自更高版本，禁止用旧平台打开')
        pending = [(v, statements(sql, version=v)) for v, sql in MIGRATIONS if v > current]
        if not pending:
            return
        # 不备份空库；旧库在任何 DDL 之前备份，包含未版本化的 0 版数据库。
        if db.execute("select 1 from sqlite_master where type='table' limit 1").fetchone():
            directory = data_dir / 'backups'
            directory.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            _backup(db, directory / f'{stamp}-{current}.db')
        db.execute('begin immediate')
        try:
            db.execute('create table if not exists schema_versions(version integer primary key, applied_at real not null)')
            # 另一连接可能在取得写锁前已经完成同一升级。
            applied = db.execute('select coalesce(max(version), 0) from schema_versions').fetchone()[0]
            for version, sqls in pending:
                if version <= applied:
                    continue
                for sql in sqls:
                    db.execute(sql)
                db.execute('insert into schema_versions values (?,?)', (version, time.time()))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    except Exception as error:
        raise RuntimeError(f'数据库升级失败（旧版本 {current}）：{error}；平台拒绝启动，请检查迁移并从 data/backups 恢复') from error
