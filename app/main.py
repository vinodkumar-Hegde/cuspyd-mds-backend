"""HTTP application boundary. PostgreSQL, authorization and scoring live here."""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import settings
from app.database import Sessions

log = logging.getLogger('mdslate.api')
app = FastAPI(title='MDSLate API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=settings().origins,
                   allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
                   allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'],
                   expose_headers=['Content-Disposition', 'X-Request-ID'])


@app.middleware('http')
async def response_headers(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(IntegrityError)
def integrity_error(request: Request, exc: IntegrityError):
    log.warning('Database constraint conflict request=%s', getattr(request.state, 'request_id', 'unknown'))
    return JSONResponse(status_code=409, content={'detail': 'Operation conflicts with an existing record'})


@app.exception_handler(SQLAlchemyError)
def database_error(request: Request, exc: SQLAlchemyError):
    log.error('Database unavailable request=%s error=%s',
              getattr(request.state, 'request_id', 'unknown'), type(exc).__name__)
    return JSONResponse(status_code=503, content={'detail': 'Service temporarily unavailable'})


@app.get('/health')
def health():
    return {'ok': True}


@app.get('/ready')
def ready():
    with Sessions() as session:
        session.execute(text('SELECT 1 FROM public.schema_migrations WHERE version=:version'),
                        {'version': '008_production.sql'}).scalar_one()
    return {'ok': True}


from app.auth import router as auth_router
from app.auth_email import router as email_router
from app.routes_v1 import router as v1_router
from app.resources import router as resource_router
from app.operations import router as operations_router
from app.uploads import router as upload_router
from app.import_questions import router as import_router

for router in (auth_router, email_router, v1_router, resource_router, operations_router, upload_router, import_router):
    app.include_router(router)
