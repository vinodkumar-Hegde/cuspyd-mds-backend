"""Bounded resource pages with an explicit total; no silent list truncation."""
from fastapi import Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def page(session: Session, statement: Select, response: Response, limit: int, offset: int):
    total = session.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one()
    response.headers['X-Total-Count'] = str(total)
    records = session.execute(statement.limit(limit).offset(offset)).mappings().all()
    return jsonable_encoder([dict(record) for record in records])
