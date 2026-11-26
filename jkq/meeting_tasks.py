"""会议收件箱的唯一办理状态；沿用旧完成表，兼容已知完成事实。"""
import json
from datetime import datetime, timezone


def ensure_columns(db):
    columns = {row[1] for row in db.execute('pragma table_info(jkq_meeting_todo_done)')}
    for name, definition in [('status', "text not null default '已完成'"), ('note', "text not null default ''"), ('history', "text not null default '[]'")]:
        if name not in columns:
            db.execute(f'alter table jkq_meeting_todo_done add column {name} {definition}')


def task_state(store, assignment):
    with store._lock:
        row = store._db.execute('select status,note,history from jkq_meeting_todo_done where owner=? and id=?',
                                (assignment['recipientId'], assignment['id'])).fetchone()
    return {'status': row[0], 'note': row[1], 'history': json.loads(row[2])} if row else {'status': '待处理', 'note': '', 'history': []}


def update_task(store, assignment, status, note, actor):
    with store._lock, store._db as db:
        store.begin_write()
        previous = task_state(store, assignment)
        history = previous['history'] + [{'from': previous['status'], 'to': status, 'note': note, 'by': actor,
                                         'at': datetime.now(timezone.utc).isoformat()}]
        db.execute('insert into jkq_meeting_todo_done(owner,id,status,note,history) values (?,?,?,?,?) '
                   'on conflict(owner,id) do update set status=excluded.status,note=excluded.note,history=excluded.history',
                   (assignment['recipientId'], assignment['id'], status, note, json.dumps(history, ensure_ascii=False)))
        store.audit('meeting', actor, 'todo.progress', {'id': assignment['id'], 'status': status}, connection=db)


def install_reassignment(db):
    """在平台保存新版本的同一个 SQLite 事务中同步接收人、状态、通知和审计。"""
    # 不在 SDK save_record 外嵌套连接 context：其内部提交会拆开事务。
    # 标记仅对指定的新版本生效，后续普通修订保留标记也不会重复执行。
    db.executescript("""
    CREATE TRIGGER IF NOT EXISTS meeting_assignment_change_atomic
    BEFORE INSERT ON v1_versions
    WHEN json_extract(NEW.document, '$.appId')='meeting'
      AND json_extract(NEW.document, '$.data.assignmentChange.version')=NEW.version
    BEGIN
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM v1_versions old, json_each(old.document, '$.data.todos') task
        WHERE old.record_id=NEW.record_id AND old.version=NEW.version-1
          AND json_extract(task.value,'$.id')=json_extract(NEW.document,'$.data.assignmentChange.todoId')
          AND json_extract(task.value,'$.assignment.recipientId')=json_extract(NEW.document,'$.data.assignmentChange.previousOwnerId')
          AND json_extract(task.value,'$.due')=json_extract(NEW.document,'$.data.assignmentChange.previousDue')
      ) THEN RAISE(ABORT, 'meeting_assignment_conflict') END;
      SELECT CASE WHEN EXISTS (
        SELECT 1 FROM jkq_meeting_todo_done
        WHERE id=json_extract(NEW.document,'$.data.assignmentChange.assignmentId')
          AND owner=json_extract(NEW.document,'$.data.assignmentChange.previousOwnerId')
          AND status IN ('已完成','已取消')
      ) THEN RAISE(ABORT, 'meeting_assignment_closed') END;
      INSERT INTO jkq_meeting_todo_done(owner,id,status,note,history)
      VALUES (
        json_extract(NEW.document,'$.data.assignmentChange.ownerId'),
        json_extract(NEW.document,'$.data.assignmentChange.assignmentId'),
        COALESCE((SELECT status FROM jkq_meeting_todo_done WHERE id=json_extract(NEW.document,'$.data.assignmentChange.assignmentId') AND owner=json_extract(NEW.document,'$.data.assignmentChange.previousOwnerId')),'待处理'),
        json_extract(NEW.document,'$.data.assignmentChange.note'),
        json_insert(COALESCE((SELECT history FROM jkq_meeting_todo_done WHERE id=json_extract(NEW.document,'$.data.assignmentChange.assignmentId') AND owner=json_extract(NEW.document,'$.data.assignmentChange.previousOwnerId')),'[]'), '$[#]', json_extract(NEW.document,'$.data.assignmentChange'))
      ) ON CONFLICT(owner,id) DO UPDATE SET status=excluded.status,note=excluded.note,history=excluded.history;
      DELETE FROM jkq_meeting_todo_done
      WHERE id=json_extract(NEW.document,'$.data.assignmentChange.assignmentId')
        AND owner=json_extract(NEW.document,'$.data.assignmentChange.previousOwnerId')
        AND owner<>json_extract(NEW.document,'$.data.assignmentChange.ownerId');
      INSERT INTO v1_notifications(id,app,recipient,project,document)
      SELECT 'meeting-adjust:'||NEW.record_id||':'||NEW.version||':'||recipient.value,
        'meeting',recipient.value,json_extract(NEW.document,'$.project'),
        json_object('id','meeting-adjust:'||NEW.record_id||':'||NEW.version||':'||recipient.value,
          'appId','meeting','recordId',NEW.record_id,'version',NEW.version,'recipient',recipient.value,
          'project',json_extract(NEW.document,'$.project'),
          'source',json_object('appId','meeting','recordId',NEW.record_id,'version',NEW.version),
          'message',json_extract(NEW.document,'$.data.assignmentChange.message'),
          'title','会议事项调整','senderId',json_extract(NEW.document,'$.submitter'),
          'createdAt',json_extract(NEW.document,'$.createdAt'))
      FROM json_each(NEW.document,'$.data.assignmentChange.recipients') recipient;
      INSERT INTO audit(ts,app_id,user_id,action,detail)
      VALUES(json_extract(NEW.document,'$.createdAt'),'meeting',json_extract(NEW.document,'$.submitter'),
        'meeting.todo.reassign',json_extract(NEW.document,'$.data.assignmentChange'));
    END;
    """)
