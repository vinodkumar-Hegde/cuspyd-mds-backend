"""Request-scoped database sessions and cached, allowlisted schema reflection."""
from functools import lru_cache

from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings().database_url, pool_pre_ping=True, pool_recycle=1800,
                       connect_args={'options': '-c statement_timeout=15000 -c lock_timeout=5000'})
Sessions = sessionmaker(engine, expire_on_commit=False)
TABLES = frozenset({'app_users', 'questions', 'tests', 'exam_sessions',
                   'feature_settings', 'high_yield_topics', 'subject_backgrounds',
                   'flow_chart_questions', 'syndromes', 'subjects'})


def db():
    with Sessions() as session:
        yield session


@lru_cache(maxsize=len(TABLES))
def table(name: str) -> Table:
    if name not in TABLES:
        raise ValueError('Unknown resource')
    return Table(name, MetaData(), autoload_with=engine, schema='public')
