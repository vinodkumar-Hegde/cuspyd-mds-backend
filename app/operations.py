"""Read-only analytics and explicitly authorized exports for MDSLate.

Statistics read canonical result snapshots. Administrator exports use fixed
dataset/column allowlists and never expose credentials.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import db
from app.security import admin, authenticated

router = APIRouter(prefix='/api/v1', tags=['operations'])
log = logging.getLogger('mdslate.audit')

EXPORT_COLUMNS = {
    'questions': ('id','subject_id','year','text','options','correct_option','explanation','topic','image_url'),
    'tests': ('id','title','type','status','questions','created_at','answer_key','explanations','admin_message'),
    'high_yield_topics': ('id','subject_id','year','topic_name','created_at','question_image_url','answer_image_url'),
}
FILTER_FIELDS = {
    'questions': ('subject_id','year'),
    'tests': ('type','status'),
    'high_yield_topics': ('subject_id','year'),
}
CSV_FORMULA = re.compile(r'^\s*[=+\-@\t\r\n]')


def safe_cell(value: Any) -> str:
    """Neutralize spreadsheet formula injection when exporting untrusted text."""
    if value is None:
        return ''
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(jsonable_encoder(value), ensure_ascii=False)
    elif isinstance(value, (datetime, date)):
        value = value.isoformat()
    else:
        value = str(value)
    return "'" + value if CSV_FORMULA.match(value) else value


def score_from_payload(payload: Any) -> dict[str, float] | None:
    if not isinstance(payload, dict):
        return None
    try:
        out = {k:float(payload[k]) for k in ('score', 'correct','wrong','unattempted')}
    except (TypeError, ValueError, KeyError, OverflowError):
        return None
    if any(not (-100000 <= v <= 100000) for v in out.values()):
        return None
    return out


def rows(session: Session, sql: str, args: dict | None = None) -> list[dict]:
    return [dict(r) for r in session.execute(text(sql), args or {}).mappings().all()]


def scalar(session: Session, sql: str, args: dict | None = None) -> int:
    return int(session.execute(text(sql), args or {}).scalar_one())


@router.get('/stats/overview')
def stats_overview(user: dict = Depends(authenticated), session: Session = Depends(db)):
    """Real DB metrics, with all personal exam statistics scoped to authenticated user."""
    uid = user['id']
    try:
        questions = scalar(session, 'SELECT count(*) FROM public.questions')
        image_questions = scalar(session, 'SELECT count(*) FROM public.questions WHERE image_url IS NOT NULL')
        tests_total = scalar(session, 'SELECT count(*) FROM public.tests')
        active_tests = scalar(session, "SELECT count(*) FROM public.tests WHERE status='PUBLISHED' OR (status='SCHEDULED' AND publish_date<=now())")
        subjects_total = scalar(session, 'SELECT count(DISTINCT subject_id) FROM public.questions')
        # Only current user's completed sessions, not all students' exam answers.
        completed = scalar(session, 'SELECT count(*) FROM public.exam_sessions WHERE user_id=:uid AND is_completed=true', {'uid': uid})
        recent = rows(session, '''
            SELECT id, type, COALESCE(end_time,start_time) AS completed_at,
                   result_snapshot->'results' AS results, result_snapshot->>'scoring_source' AS scoring_source
            FROM public.exam_sessions
            WHERE user_id=:uid AND is_completed=true
            ORDER BY COALESCE(end_time,start_time) DESC LIMIT 500
        ''', {'uid':uid})
        scored = [m for r in recent if r['scoring_source']=='server' and (m:=score_from_payload(r['results'])) is not None]
        score_avg = round(sum(s['score'] for s in scored)/len(scored), 1) if scored else None
        denominator = sum(s['correct']+s['wrong']+s['unattempted'] for s in scored)
        accuracy = round(100*sum(s['correct'] for s in scored)/denominator, 1) if denominator else None
        today = datetime.now(timezone.utc).date()
        days = { (today-timedelta(days=d)).isoformat():0 for d in range(6,-1,-1)}
        daily = rows(session, '''
            SELECT (COALESCE(end_time,start_time) AT TIME ZONE 'UTC')::date AS day, count(*)::int AS attempts
            FROM public.exam_sessions
            WHERE user_id=:uid AND is_completed=true
                  AND COALESCE(end_time,start_time) >= now() - interval '7 days'
            GROUP BY 1 ORDER BY 1
        ''', {'uid':uid})
        for r in daily:
            key=r['day'].isoformat()
            if key in days:days[key]=r['attempts']
        result={
            'question_count':questions, 'question_images':image_questions,
            'test_count':tests_total, 'available_tests':active_tests,
            'subject_count':subjects_total, 'my_completed_exams':completed,
            'my_average_score_last_500':score_avg, 'my_accuracy_last_500':accuracy,
            'my_activity_7d':[{'date':k,'attempts':v} for k,v in days.items()],
            'my_recent_exams':[{'id':str(r['id']), 'type':r['type'], 'completed_at':r['completed_at'],
                               'score':(s or {}).get('score')}
                              for r in recent[:5] for s in [score_from_payload(r['results'])]],
            'metrics_sample_size':len(scored),
            'is_admin':user['role']=='admin',
        }
        if user['role']=='admin':
            result['admin']={
                'account_count':scalar(session,'SELECT count(*) FROM public.app_users'),
                'disabled_accounts':scalar(session,'SELECT count(*) FROM public.app_users WHERE NOT is_active'),
                'total_completed_exams':scalar(session,'SELECT count(*) FROM public.exam_sessions WHERE is_completed=true'),
            }
        return result
    except SQLAlchemyError:
        log.exception('Dashboard statistics database query failed')
        raise HTTPException(503,'Statistics temporarily unavailable') from None


@router.get('/stats/subjects')
def stats_subjects(user: dict = Depends(authenticated), session: Session = Depends(db)):
    try:
        return rows(session, '''
            SELECT subject_id AS subject, count(*)::int AS questions,
                   count(*) FILTER (WHERE image_url IS NOT NULL)::int AS image_questions
            FROM public.questions GROUP BY subject_id ORDER BY questions DESC, subject LIMIT 50
        ''')
    except SQLAlchemyError:
        log.exception('Subject stats database query failed')
        raise HTTPException(503,'Statistics temporarily unavailable') from None


@router.get('/admin/exports/{dataset}')
def export_dataset(
    dataset: Literal['questions','tests','high_yield_topics'],
    format: Literal['csv','xlsx','json'] = Query('csv'),
    filter_value: str | None = Query(None, min_length=1, max_length=80),
    filter_by: str | None = Query(None, min_length=1, max_length=40),
    actor: dict = Depends(admin), session: Session = Depends(db),
):
    """Export is admin-only and allowlisted; never interpolates user SQL."""
    if (filter_by is None) != (filter_value is None):
        raise HTTPException(422,'Filter field and value must both be provided')
    if filter_by is not None and filter_by not in FILTER_FIELDS[dataset]:
        raise HTTPException(422,'Invalid filter for this dataset')
    cols = EXPORT_COLUMNS[dataset]
    # SQL identifiers come exclusively from constants above.
    query=f'SELECT {", ".join(cols)} FROM public.{dataset}'
    args:dict[str,str]={}
    if filter_by is not None:
        query+=f' WHERE {filter_by} = :filter_value'
        args['filter_value']=filter_value
    query+=f' ORDER BY {cols[0]} LIMIT 10001'
    try:
        result=rows(session, query, args)
        if len(result)>10000:
            raise HTTPException(413,'Export exceeds 10,000 rows; filter the dataset')
        # Persistent audit required for sensitive exports; migration included.
        session.execute(text('''
            INSERT INTO public.export_audit_events (actor_id,dataset,format,row_count,filter_by)
            VALUES (:actor,:dataset,:format,:count,:filter)
        '''), {'actor':actor['id'], 'dataset':dataset, 'format':format,
               'count':len(result),'filter':filter_by})
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError:
        session.rollback()
        log.exception('Export failed (did you apply 006_export_audit.sql?)')
        raise HTTPException(503,'Export unavailable; check database migration and logs') from None
    log.info('export actor=%s dataset=%s format=%s rows=%d',actor['id'],dataset,format,len(result))
    filename=f'mdslate_{dataset}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.{format}'
    headers={'Content-Disposition':f'attachment; filename="{filename}"',
             'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'}
    if format=='json':
        payload=json.dumps(jsonable_encoder(result),ensure_ascii=False).encode('utf-8')
        return Response(payload,media_type='application/json',headers=headers)
    if format=='csv':
        buffer=io.StringIO(newline='')
        writer=csv.writer(buffer)
        writer.writerow(cols)
        for r in result: writer.writerow([safe_cell(r.get(c)) for c in cols])
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8', headers=headers)
    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise HTTPException(503,'XLSX export dependency unavailable') from None
    workbook=Workbook(write_only=False)
    sheet=workbook.active
    sheet.title=dataset[:31]
    sheet.append(list(cols))
    for r in result:sheet.append([safe_cell(r.get(c)) for c in cols])
    sheet.freeze_panes='A2'
    sheet.auto_filter.ref=sheet.dimensions
    for cell in sheet[1]:
        cell.font=Font(bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid', fgColor='1E3A5F')
    for index,col in enumerate(cols,1):
        sheet.column_dimensions[get_column_letter(index)].width=min(54,max(14,len(col)+3))
    out=io.BytesIO()
    workbook.save(out)
    return Response(out.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers=headers)

@router.get('/admin/activity')
def admin_activity(actor: dict = Depends(admin), session: Session = Depends(db)):
    """Limited admin activity summary, no answer JSON or password data."""
    try:
        result=rows(session, '''
            SELECT e.id, e.type, e.is_completed, e.start_time, e.end_time,
                   u.name AS student_name, u.email AS student_email
            FROM public.exam_sessions e
            LEFT JOIN public.app_users u ON u.id=e.user_id
            ORDER BY e.start_time DESC LIMIT 200
        ''')
        return jsonable_encoder(result)
    except SQLAlchemyError:
        log.exception('Admin activity query failed')
        raise HTTPException(503,'Activity temporarily unavailable') from None


def performance_summary(user: dict, session: Session) -> dict:
    data = rows(session, '''
        SELECT result_snapshot FROM public.exam_sessions
        WHERE user_id=:uid AND is_completed=true AND result_snapshot->>'scoring_source'='server'
        ORDER BY end_time DESC LIMIT 500
    ''', {'uid': user['id']})
    subjects: dict[str, dict] = {}
    scores = []
    for row in data:
        snapshot = row['result_snapshot']
        result = snapshot['results']
        total = result['correct'] + result['wrong'] + result['unattempted']
        if total:
            scores.append(100 * result['correct'] / total)
        for question in snapshot['questions']:
            stat = subjects.setdefault(question['subjectId'], {'correct': 0, 'total': 0})
            stat['total'] += 1
            stat['correct'] += int(result['answers'].get(question['id']) == question['correctOption'])
    return {'averageScore': round(sum(scores) / len(scores), 1) if scores else None,
            'subjects': [{'subject_id': key, **value, 'accuracy': round(100*value['correct']/value['total'], 1)}
                         for key, value in subjects.items()], 'attempts': len(data)}


@router.get('/stats/performance')
def performance(user: dict = Depends(authenticated), session: Session = Depends(db)):
    return performance_summary(user, session)


@router.get('/leaderboard')
def leaderboard(user: dict = Depends(authenticated), session: Session = Depends(db)):
    # Only server-scored snapshots qualify; no client-submitted legacy scores.
    return rows(session, '''
        WITH best AS (
            SELECT user_id, max((result_snapshot->'results'->>'score')::integer) AS score
            FROM public.exam_sessions
            WHERE type='RANKER' AND is_completed=true AND result_snapshot->>'scoring_source'='server'
            GROUP BY user_id
        )
        SELECT dense_rank() OVER (ORDER BY b.score DESC) AS rank,
               u.id, u.name, u.college, b.score
        FROM best b JOIN public.app_users u ON u.id=b.user_id
        WHERE u.is_active=true
        ORDER BY b.score DESC, u.id LIMIT 200
    ''')
