"""Explicit resource APIs. Clients cannot select tables, columns or SQL operators."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import db, table
from app.pagination import page
from app.security import admin, authenticated, feature

router = APIRouter(prefix='/api/v1', tags=['resources'])


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class QuestionInput(Input):
    subject_id: str = Field(min_length=1, max_length=80)
    year: Literal['BDS-I', 'BDS-II', 'BDS-III', 'BDS-IV']
    text: str = Field(min_length=1, max_length=12000)
    options: list[Annotated[str, Field(min_length=1, max_length=4000)]] = Field(min_length=4, max_length=4)
    correct_option: int = Field(strict=True, ge=0, le=3)
    explanation: str = Field(default='', max_length=16000)
    topic: str | None = Field(default=None, max_length=300)
    image_url: str | None = Field(default=None, max_length=2000)
    image_practice_enabled: bool = False

    @model_validator(mode='after')
    def published_image(self):
        if self.image_practice_enabled and not self.image_url:
            raise ValueError('Image practice requires an image')
        return self


class TestInput(Input):
    title: str = Field(min_length=1, max_length=200)
    type: Literal['ST', 'MT', 'GT', 'RANKER', 'MOCK']
    status: Literal['DRAFT', 'LOCKED', 'PUBLISHED', 'SCHEDULED', 'ARCHIVED'] = 'DRAFT'
    questions: list[UUID] = Field(min_length=1, max_length=500)
    publish_date: datetime | None = None
    subject_id: str | None = None
    weightage: dict[str, Annotated[int, Field(strict=True, ge=0, le=500)]] = Field(default_factory=dict, max_length=40)
    admin_message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def valid_schedule(self):
        if len(set(self.questions)) != len(self.questions):
            raise ValueError('An exam cannot repeat a question')
        if self.status == 'SCHEDULED':
            if not self.publish_date or not self.publish_date.tzinfo or self.publish_date <= datetime.now(timezone.utc):
                raise ValueError('Scheduled exams need a future release date with a timezone')
        return self


class TestPatch(Input):
    admin_message: str | None = Field(default=None, max_length=2000)
    status: Literal['DRAFT', 'LOCKED', 'PUBLISHED', 'ARCHIVED'] | None = None


class TestArchive(Input):
    type: Literal['ST', 'MT', 'GT', 'RANKER', 'MOCK'] | None = None


class Selection(Input):
    weightage: dict[str, Annotated[int, Field(strict=True, ge=0, le=500)]] = Field(min_length=1, max_length=40)


class HighYieldInput(Input):
    subject_id: str = Field(min_length=1, max_length=80)
    year: str = Field(min_length=1, max_length=30)
    topic_name: str = Field(min_length=1, max_length=300)
    question_image_url: str = Field(min_length=1, max_length=2000)
    answer_image_url: str = Field(min_length=1, max_length=2000)


class SyndromeInput(Input):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=8000)
    image_url: str = Field(min_length=1, max_length=2000)


class BackgroundInput(Input):
    subject_name: str = Field(min_length=1, max_length=200)
    image_url: str = Field(min_length=1, max_length=2000)


class FlowchartInput(Input):
    subject_id: str | None = None
    question_text: str = Field(min_length=1, max_length=4000)
    correct_answer: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=8000)
    generated_flowchart: dict

    @field_validator('generated_flowchart')
    @classmethod
    def validate_flowchart(cls, value):
        if (not isinstance(value.get('nodes'), list) or not isinstance(value.get('edges'), list)
                or len(value['nodes']) > 100 or len(value['edges']) > 250):
            raise ValueError('Invalid flowchart')
        return value


class FeaturePatch(Input):
    is_visible: bool


def subject_exists(session: Session, subject: str | None):
    if subject and not session.execute(select(table('subjects').c.id).where(table('subjects').c.id == subject)).first():
        raise HTTPException(422, 'Unknown subject')


def create_rows(session: Session, name: str, values: list[dict]):
    t = table(name)
    records = [dict(row) for row in session.execute(insert(t).values(values).returning(t)).mappings()]
    session.commit()
    return records


def list_rows(session: Session, name: str, limit: int, offset: int, subject_id: str | None = None):
    t = table(name)
    stmt = select(t)
    if subject_id:
        stmt = stmt.where(t.c.subject_id == subject_id)
    key = t.c.id if 'id' in t.c else t.c.feature_key
    return [dict(row) for row in session.execute(stmt.order_by(key).limit(limit).offset(offset)).mappings()]


@router.get('/catalog')
def catalog(session: Session = Depends(db)):
    return {'subjects': list_rows(session, 'subjects', 100, 0),
            'exam_seconds_per_question': settings().exam_seconds_per_question}


@router.get('/admin/questions', dependencies=[Depends(admin)])
def questions(response: Response, subject_id: str | None = None, year: str | None = None,
              limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000),
              session: Session = Depends(db)):
    t = table('questions')
    statement = select(t)
    if subject_id:
        statement = statement.where(t.c.subject_id == subject_id)
    if year:
        statement = statement.where(t.c.year == year)
    return page(session, statement.order_by(t.c.id), response, limit, offset)


@router.get('/admin/question-counts', dependencies=[Depends(admin)])
def question_counts(session: Session = Depends(db)):
    t = table('questions')
    return {row.subject_id: row.total for row in session.execute(select(t.c.subject_id, func.count().label('total')).group_by(t.c.subject_id))}


@router.post('/admin/questions', status_code=201, dependencies=[Depends(admin)])
def create_questions(body: list[QuestionInput], session: Session = Depends(db)):
    if not 1 <= len(body) <= 1000:
        raise HTTPException(422, 'Upload between 1 and 1,000 questions at a time')
    for subject in {q.subject_id for q in body}:
        subject_exists(session, subject)
    return create_rows(session, 'questions', [q.model_dump() for q in body])


@router.patch('/admin/questions/{question_id}', dependencies=[Depends(admin)])
def edit_question(question_id: UUID, body: QuestionInput, session: Session = Depends(db)):
    subject_exists(session, body.subject_id)
    t = table('questions')
    row = session.execute(update(t).where(t.c.id == question_id).values(**body.model_dump()).returning(t)).mappings().first()
    if not row:
        raise HTTPException(404, 'Question not found')
    session.commit()
    return dict(row)


@router.post('/admin/question-selection', dependencies=[Depends(admin)])
def select_questions(body: Selection, session: Session = Depends(db)):
    total = sum(body.weightage.values())
    if not 1 <= total <= 500:
        raise HTTPException(422, 'Choose between 1 and 500 questions')
    q = table('questions')
    picked = []
    for subject, count in body.weightage.items():
        if count == 0:
            continue
        subject_exists(session, subject)
        subset = session.execute(select(q).where(q.c.subject_id == subject).order_by(func.random()).limit(count)).mappings().all()
        if len(subset) != count:
            raise HTTPException(409, f'Insufficient questions for {subject}; requested {count}, available {len(subset)}')
        picked.extend(dict(row) for row in subset)
    return picked


@router.get('/admin/tests', dependencies=[Depends(admin)])
def tests(response: Response, include_archived: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), session: Session = Depends(db)):
    t = table('tests')
    statement = select(t)
    if not include_archived:
        statement = statement.where(t.c.status != 'ARCHIVED')
    return page(session, statement.order_by(t.c.created_at.desc(), t.c.id), response, limit, offset)


@router.post('/admin/tests', status_code=201, dependencies=[Depends(admin)])
def create_test(body: TestInput, session: Session = Depends(db)):
    subject_exists(session, body.subject_id)
    q = table('questions')
    found = session.execute(select(func.count()).select_from(q).where(q.c.id.in_(body.questions))).scalar_one()
    if found != len(body.questions):
        raise HTTPException(422, 'Exam contains unknown questions')
    values = body.model_dump()
    values['questions'] = [str(uid) for uid in body.questions]
    return create_rows(session, 'tests', [values])[0]


@router.patch('/admin/tests/{test_id}', dependencies=[Depends(admin)])
def edit_test(test_id: UUID, body: TestPatch, session: Session = Depends(db)):
    t = table('tests')
    values = body.model_dump(exclude_unset=True)
    if not values or values.get('status', '') is None:
        raise HTTPException(422, 'Provide a valid test change')
    row = session.execute(update(t).where(t.c.id == test_id).values(**values).returning(t)).mappings().first()
    if not row:
        raise HTTPException(404, 'Exam not found')
    session.commit()
    return dict(row)


@router.delete('/admin/tests/{test_id}', status_code=204, dependencies=[Depends(admin)])
def archive_test(test_id: UUID, session: Session = Depends(db)):
    t = table('tests')
    result = session.execute(update(t).where(t.c.id == test_id).values(status='ARCHIVED'))
    if not result.rowcount:
        raise HTTPException(404, 'Exam not found')
    session.commit()


@router.post('/admin/tests/archive', dependencies=[Depends(admin)])
def archive_tests(body: TestArchive, session: Session = Depends(db)):
    t = table('tests')
    stmt = update(t).where(t.c.status != 'ARCHIVED')
    if body.type:
        stmt = stmt.where(t.c.type == body.type)
    result = session.execute(stmt.values(status='ARCHIVED'))
    session.commit()
    return {'archived': result.rowcount}


@router.get('/admin/users', dependencies=[Depends(admin)])
def users(response: Response, search: str = Query('', max_length=160), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), session: Session = Depends(db)):
    u = table('app_users')
    cols = [u.c[key] for key in ('id','name','email','college','state','role','created_at','is_active')]
    statement = select(*cols, u.c.mobile_e164.label('mobile'))
    if search.strip():
        statement = statement.where(or_(u.c.name.ilike(f'%{search.strip()}%'), u.c.email.ilike(f'%{search.strip()}%')))
    return page(session, statement.order_by(u.c.created_at.desc(), u.c.id), response, limit, offset)


@router.post('/admin/high-yield', status_code=201, dependencies=[Depends(admin)])
def create_high_yield(body: HighYieldInput, session: Session = Depends(db)):
    subject_exists(session, body.subject_id)
    return create_rows(session, 'high_yield_topics', [body.model_dump()])[0]


@router.delete('/admin/high-yield/{topic_id}', status_code=204, dependencies=[Depends(admin)])
def delete_high_yield(topic_id: UUID, session: Session = Depends(db)):
    t = table('high_yield_topics')
    if not session.execute(delete(t).where(t.c.id == topic_id)).rowcount:
        raise HTTPException(404, 'Topic not found')
    session.commit()


@router.post('/admin/syndromes', status_code=201, dependencies=[Depends(admin)])
def create_syndrome(body: SyndromeInput, session: Session = Depends(db)):
    return create_rows(session, 'syndromes', [body.model_dump()])[0]


@router.get('/content/subject-backgrounds', dependencies=[Depends(authenticated)])
def backgrounds(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), session: Session = Depends(db)):
    t = table('subject_backgrounds')
    return page(session, select(t).order_by(t.c.subject_name, t.c.id), response, limit, offset)


@router.post('/admin/subject-backgrounds', status_code=201, dependencies=[Depends(admin)])
def create_background(body: BackgroundInput, session: Session = Depends(db)):
    return create_rows(session, 'subject_backgrounds', [body.model_dump()])[0]


@router.get('/content/flowcharts', dependencies=[Depends(feature('flow_charts'))])
def flowcharts(response: Response, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000), session: Session = Depends(db)):
    t = table('flow_chart_questions')
    return page(session, select(t).order_by(t.c.created_at.desc(), t.c.id), response, limit, offset)


@router.post('/admin/flowcharts', status_code=201, dependencies=[Depends(admin)])
def create_flowcharts(body: list[FlowchartInput], session: Session = Depends(db)):
    if not 1 <= len(body) <= 100:
        raise HTTPException(422, 'Upload between 1 and 100 flowcharts')
    for item in body:
        subject_exists(session, item.subject_id)
    return create_rows(session, 'flow_chart_questions', [item.model_dump() for item in body])


@router.patch('/admin/features/{key}', dependencies=[Depends(admin)])
def toggle_feature(key: str, body: FeaturePatch, session: Session = Depends(db)):
    t = table('feature_settings')
    if not session.execute(update(t).where(t.c.feature_key == key).values(is_visible=body.is_visible)).rowcount:
        raise HTTPException(404, 'Feature not found')
    session.commit()
    return body.model_dump()
