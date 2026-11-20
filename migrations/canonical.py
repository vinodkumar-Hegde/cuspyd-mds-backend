"""Convert historical data once. The HTTP application never imports this module."""
import math
from uuid import UUID

from sqlalchemy import MetaData, Table, bindparam, inspect, select, update

RETIRED_TABLES = ('profiles', 'user_profiles', 'user_performance', 'exam_attempts',
                  'high_yield_questions', 'dashboard_content', 'app_settings')


def historical_snapshot(record: dict) -> dict:
    payload = record['answers'] if isinstance(record['answers'], dict) else {}
    body = payload.get('results') if isinstance(payload.get('results'), dict) else payload
    supplied_answers = body.get('answers') if isinstance(body.get('answers'), dict) else body
    answers = {}
    for key, value in supplied_answers.items():
        try:
            question_id = str(UUID(str(key)))
        except (ValueError, TypeError):
            continue
        if type(value) is int and 0 <= value <= 3:
            answers[question_id] = value
    summary = {}
    for key in ('score', 'correct', 'wrong', 'unattempted'):
        value = body.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            summary = None
            break
        if key != 'score' and (value < 0 or int(value) != value):
            summary = None
            break
        summary[key] = value
    if summary is not None:
        summary['answers'] = answers
    return {
        'schema_version': 1, 'scoring_source': 'imported', 'review_available': False,
        'session_id': str(record['id']),
        'test': {'id': str(record['test_id']) if record['test_id'] else None,
                 'title': record['test_title'] or 'Historical exam', 'type': record['type'],
                 'status': record['test_status'], 'questions': list(answers)},
        'results': summary, 'questions': [],
        'notice': ('Only the originally saved score is available for this attempt. Detailed question review was not saved.'
                   if summary is not None else
                   'This attempt has no saved score or question review. Its original answers are preserved.'),
    }


def migrate(connection):
    metadata = MetaData()
    attempts = Table('exam_sessions', metadata, autoload_with=connection, schema='public')
    tests = Table('tests', metadata, autoload_with=connection, schema='public')
    statement = select(attempts, tests.c.title.label('test_title'), tests.c.status.label('test_status')).outerjoin(
        tests, tests.c.id == attempts.c.test_id).where(
        attempts.c.is_completed.is_(True)).order_by(attempts.c.id)
    # A finite server-side cursor keeps memory bounded without re-query loops.
    records = connection.execution_options(stream_results=True).execute(statement).mappings()
    write = update(attempts).where(attempts.c.id == bindparam('attempt_id')).values(
        result_snapshot=bindparam('snapshot'))
    for batch in records.partitions(500):
        converted = []
        for record in batch:
            if record['result_snapshot'] is None:
                snapshot = historical_snapshot(dict(record))
            elif isinstance(record['result_snapshot'], dict):
                snapshot = dict(record['result_snapshot'])
                snapshot.setdefault('schema_version', 1)
                snapshot.setdefault('scoring_source', 'server')
                snapshot.setdefault('review_available', bool(snapshot.get('questions')))
            else:
                raise RuntimeError('Invalid saved result snapshot; repair corrupted data before migrating')
            converted.append({'attempt_id': record['id'], 'snapshot': snapshot})
        connection.execution_options(stream_results=False).execute(write, converted)
    records.close()
    connection.exec_driver_sql('''ALTER TABLE public.exam_sessions ADD CONSTRAINT completed_attempt_snapshot
        CHECK (NOT is_completed OR result_snapshot IS NOT NULL)''')
    available = set(inspect(connection).get_table_names(schema='public'))
    for name in RETIRED_TABLES:
        if name in available:
            # Identifiers are migration-owned constants, never request values.
            connection.exec_driver_sql(f'ALTER TABLE public.{name} SET SCHEMA retired')
