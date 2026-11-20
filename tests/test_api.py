"""Real PostgreSQL API tests. No production database or real email delivery."""
import io
import os
import smtplib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import auth_email
from app.database import engine
from app.migrate import migrate

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Set TEST_DATABASE_URL to a disposable PostgreSQL database')
from factories import PASSWORD, account, details, exam, register


def test_complete_registration_login_and_profile(client):
    assert register(client).status_code == 200
    result = client.post('/api/auth/login', json={'email':' STUDENT@example.org ', 'password':PASSWORD})
    assert result.status_code == 200, result.text
    identity = client.get('/api/auth/me', headers={'Authorization':'Bearer '+result.json()['access_token']})
    assert identity.json()['mobile'] == '+919876543210'
    assert identity.json()['role'] == 'student'
    assert 'password_hash' not in identity.json()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.app_users')).scalar_one() == 1


def test_duplicate_email_case_insensitive(client):
    assert register(client).status_code == 200
    response = client.post('/api/auth/register/request', json=details('STUDENT@example.org', '9876543211'))
    assert response.status_code == 409
    assert 'email' in response.json()['detail']
    assert len(client.sent) == 1


@pytest.mark.parametrize('mobile', ['98765 43210', '+91 98765-43210', '09876543210'])
def test_duplicate_mobile_formats(client, mobile):
    assert register(client).status_code == 200
    response = client.post('/api/auth/register/request', json=details('another@example.org', mobile))
    assert response.status_code == 409
    assert 'mobile' in response.json()['detail']


@pytest.mark.parametrize('extra', [{'mobile':'123'}, {'mobile':''}, {'password':'short'}, {'role':'admin'}, {'name':'  '}])
def test_registration_validation(client, extra):
    response = client.post('/api/auth/register/request', json={**details(), **extra})
    assert response.status_code == 422
    assert not client.sent


def test_concurrent_mobile_verification(client):
    for email in ('one@example.org','two@example.org'):
        assert client.post('/api/auth/register/request', json=details(email)).status_code == 202
    def verify(item):
        email, code, _ = item
        return client.post('/api/auth/register/verify', json={'email':email, 'code':code}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(verify, client.sent[:]))
    assert sorted(statuses) == [200,409]
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.app_users')).scalar_one() == 1


def test_database_unique_constraints(client):
    account(email='Existing@example.org', mobile='+919876543210')
    with pytest.raises(IntegrityError):
        account(email='existing@example.org', mobile='+919876543211')
    with pytest.raises(IntegrityError):
        account(email='other@example.org', mobile='+919876543210')


def test_expired_code_and_replay(client):
    assert client.post('/api/auth/register/request', json=details()).status_code == 202
    email, code, _ = client.sent[-1]
    with engine.begin() as connection:
        connection.execute(text("UPDATE public.auth_email_challenges SET expires_at=now()-interval '1 second'"))
    assert client.post('/api/auth/register/verify', json={'email':email, 'code':code}).status_code == 400


def test_verification_attempt_limit(client):
    assert client.post('/api/auth/register/request', json=details()).status_code == 202
    email, code, _ = client.sent[-1]
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(5):
        assert client.post('/api/auth/register/verify', json={'email':email, 'code':wrong}).status_code == 400
    assert client.post('/api/auth/register/verify', json={'email':email, 'code':code}).status_code == 400


def test_password_reset_and_logout_revoke_tokens(client):
    assert register(client).status_code == 200
    login = client.post('/api/auth/login', json={'email':'student@example.org','password':PASSWORD}).json()
    headers = {'Authorization':'Bearer '+login['access_token']}
    # Expire the request cooldown to test the reset without sleeping.
    with engine.begin() as connection:
        connection.execute(text("UPDATE public.auth_otp_rate_events SET created_at=now()-interval '61 seconds'"))
    assert client.post('/api/auth/password/reset/request', json={'email':'student@example.org'}).status_code == 202
    email, code, _ = client.sent[-1]
    new = PASSWORD+'new'
    assert client.post('/api/auth/password/reset/confirm', json={'email':email,'code':code,'new_password':new}).status_code == 200
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    token = client.post('/api/auth/login', json={'email':email,'password':new}).json()['access_token']
    headers = {'Authorization':'Bearer '+token}
    assert client.post('/api/auth/logout', headers=headers).status_code == 204
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert client.post('/api/auth/password/reset/confirm', json={'email':email,'code':code,'new_password':new}).status_code == 400


def test_email_delivery_failure_revokes_code(client, monkeypatch):
    def failure(*args):
        raise smtplib.SMTPException('test failure')
    monkeypatch.setattr(auth_email,'send_email',failure)
    assert client.post('/api/auth/register/request',json=details()).status_code == 503
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.auth_email_challenges')).scalar_one() == 0


def test_login_rate_limit_without_otp_configuration(client, monkeypatch):
    monkeypatch.delenv('OTP_SECRET')
    for _ in range(20):
        assert client.post('/api/auth/login',json={'email':'unknown@example.org','password':'invalid'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'unknown@example.org','password':'invalid'}).status_code == 429


def test_resource_permissions_and_no_generic_database_api(client):
    _, student = account()
    assert client.get('/api/v1/admin/users',headers=student).status_code == 403
    assert client.get('/api/v1/admin/questions',headers=student).status_code == 403
    assert client.get('/api/v1/exams').status_code == 401
    assert client.post('/api/data/profiles/query',json={'columns':'*'},headers=student).status_code == 404
    _, admin_headers = account('admin')
    users = client.get('/api/v1/admin/users',headers=admin_headers).json()
    assert users and all('password_hash' not in user and 'token_version' not in user for user in users)


def test_exam_scoring_snapshot_idempotency_and_archive(client):
    _, admin_headers = account('admin')
    _, student = account()
    exam_id, qid = exam(client, admin_headers)
    listing = client.get('/api/v1/exams',headers=student).json()
    assert len(listing) == 1 and 'answer_key' not in listing[0]
    question = client.get(f'/api/v1/exams/{exam_id}/questions',headers=student).json()[0]
    assert 'correct_option' not in question and 'explanation' not in question
    request = {'answers':{qid:1},'request_id':str(uuid.uuid4())}
    response = client.post(f'/api/v1/exams/{exam_id}/submit',json=request,headers=student)
    assert response.status_code == 200, response.text
    assert response.json()['results']['score'] == 4
    assert client.post(f'/api/v1/exams/{exam_id}/submit',json=request,headers=student).json() == response.json()
    history = client.get('/api/v1/exams/history',headers=student).json()
    assert len(history) == 1
    with engine.begin() as connection:
        connection.execute(text('UPDATE public.questions SET correct_option=3 WHERE id=:id'),{'id':uuid.UUID(qid)})
    assert client.delete(f'/api/v1/admin/tests/{exam_id}',headers=admin_headers).status_code == 204
    stored = client.get(f'/api/v1/exams/history/{history[0]["id"]}/result',headers=student)
    assert stored.json()['questions'][0]['correctOption'] == 1
    assert client.get('/api/v1/exams',headers=student).json() == []
    _, other = account()
    assert client.get(f'/api/v1/exams/history/{history[0]["id"]}/result',headers=other).status_code == 404


@pytest.mark.parametrize('answers', [{'unrelated-id':0}, {'PLACEHOLDER':True}, {'PLACEHOLDER':4}, {'PLACEHOLDER':'1'}])
def test_tampered_answers_rejected(client, answers):
    _, admin_headers = account('admin')
    _, student = account()
    exam_id, qid = exam(client, admin_headers)
    answers = {qid if k == 'PLACEHOLDER' else k:v for k,v in answers.items()}
    response = client.post(f'/api/v1/exams/{exam_id}/submit',json={'answers':answers,'request_id':str(uuid.uuid4())},headers=student)
    assert response.status_code == 422, response.text


def test_scheduled_exam_release_and_image_question(client):
    _, admin_headers = account('admin')
    _, student = account()
    exam_id, qid = exam(client,admin_headers,status='SCHEDULED',image=True)
    assert client.get('/api/v1/exams',headers=student).json() == []
    assert client.get(f'/api/v1/exams/{exam_id}/questions',headers=student).status_code == 404
    with engine.begin() as connection:
        connection.execute(text("UPDATE public.tests SET publish_date=now()-interval '1 minute' WHERE id=:id"),{'id':uuid.UUID(exam_id)})
    assert len(client.get('/api/v1/exams',headers=student).json()) == 1
    assert client.get(f'/api/v1/exams/{qid}/questions',headers=student).json()[0]['id'] == qid
    response = client.post(f'/api/v1/exams/{qid}/submit',json={'answers':{qid:0},'request_id':str(uuid.uuid4())},headers=student)
    assert response.status_code == 200 and response.json()['results']['score'] == -1


def test_upload_uses_server_filename_and_validates_content(client):
    _, admin_headers = account('admin')
    blob = io.BytesIO()
    Image.new('RGB',(2,2),'blue').save(blob,format='PNG')
    for bucket in ('question-images','syndromes','high-yield','subject-backgrounds'):
        response = client.post(f'/api/uploads/{bucket}',files={'file':('client-name.png',blob.getvalue(),'image/png')},headers=admin_headers)
        assert response.status_code == 201, response.text
        assert 'client-name' not in response.json()['path']
        assert client.get(response.json()['publicUrl']).content == blob.getvalue()
    assert client.post('/api/uploads/syndromes',files={'file':('wrong.png',b'not-an-image','image/png')},headers=admin_headers).status_code == 422
    _, student = account()
    assert client.post('/api/uploads/syndromes',files={'file':('x.png',blob.getvalue(),'image/png')},headers=student).status_code == 403


@pytest.fixture
def s3_storage(client, monkeypatch):
    import boto3
    from botocore.config import Config
    from botocore.stub import Stubber
    from app import storage
    from app.config import settings

    cfg = settings()
    for field, value in {'storage_backend':'s3', 's3_bucket':'test-media-bucket',
                         's3_prefix':'staging/images', 's3_presign_seconds':120,
                         's3_kms_key_id':''}.items():
        monkeypatch.setattr(cfg, field, value)
    sdk = boto3.client('s3', region_name='ap-south-1',
                       aws_access_key_id='test-only-key', aws_secret_access_key='test-only-secret',
                       config=Config(signature_version='s3v4'))
    monkeypatch.setattr(storage, 's3_client', lambda: sdk)
    with Stubber(sdk) as stub:
        yield stub
        stub.assert_no_pending_responses()


def test_s3_upload_keeps_stable_url_and_reads_with_expiring_signature(client, s3_storage):
    from botocore.stub import ANY
    from urllib.parse import parse_qs, urlsplit
    from app.config import settings

    _, headers = account('admin')
    blob = io.BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(blob, format='PNG')
    s3_storage.add_response('put_object', {}, {
        'Bucket':'test-media-bucket', 'Key':ANY, 'Body':blob.getvalue(),
        'ContentType':'image/png', 'Metadata':{'category':'syndromes'},
    })
    response = client.post('/api/uploads/syndromes', headers=headers,
                           files={'file':('original.png', blob.getvalue(), 'image/png')})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['publicUrl'] == f'/api/uploads/{body["path"]}'
    assert not list(settings().upload_dir.iterdir()), 'S3 uploads must not silently write local copies'
    s3_storage.add_response('head_object', {}, {
        'Bucket':'test-media-bucket', 'Key':f'staging/images/{body["path"]}',
    })
    media = client.get(body['publicUrl'], follow_redirects=False)
    assert media.status_code == 307
    signed = urlsplit(media.headers['location'])
    assert signed.scheme == 'https'
    assert signed.path.endswith(f'/staging/images/{body["path"]}')
    assert parse_qs(signed.query)['X-Amz-Expires'] == ['120']
    assert 'no-store' in media.headers['cache-control']
    assert 'X-Amz-' not in response.text


def test_s3_mode_preserves_existing_local_images(client, s3_storage):
    from app.config import settings
    name = f'{uuid.uuid4().hex}.png'
    (settings().upload_dir / name).write_bytes(b'legacy-image-content')
    response = client.get(f'/api/uploads/{name}', follow_redirects=False)
    assert response.status_code == 200
    assert response.content == b'legacy-image-content'


def test_s3_failure_is_controlled_and_does_not_fall_back_to_local(client, s3_storage):
    from app.config import settings
    _, headers = account('admin')
    blob = io.BytesIO()
    Image.new('RGB', (2, 2)).save(blob, format='PNG')
    s3_storage.add_client_error('put_object', service_error_code='AccessDenied',
                                service_message='private-provider-details', http_status_code=403)
    response = client.post('/api/uploads/syndromes', headers=headers,
                           files={'file':('x.png', blob.getvalue(), 'image/png')})
    assert response.status_code == 503
    assert 'private-provider-details' not in response.text
    assert 'publicUrl' not in response.json()
    assert not list(settings().upload_dir.iterdir())


def test_s3_missing_object_and_provider_denial_have_controlled_responses(client, s3_storage):
    url = f'/api/uploads/{uuid.uuid4().hex}.png'
    s3_storage.add_client_error('head_object', service_error_code='404', http_status_code=404)
    assert client.get(url, follow_redirects=False).status_code == 404
    s3_storage.add_client_error('head_object', service_error_code='AccessDenied', http_status_code=403)
    assert client.get(url, follow_redirects=False).status_code == 503


def test_s3_validation_and_authorization_happen_before_storage(client, s3_storage, monkeypatch):
    from app.config import settings
    _, admin_headers = account('admin')
    _, student_headers = account()
    def send(data, headers):
        return client.post('/api/uploads/syndromes', headers=headers,
                           files={'file':('x.png', data, 'image/png')})
    assert send(b'corrupt', admin_headers).status_code == 422
    assert send(b'corrupt', student_headers).status_code == 403
    monkeypatch.setattr(settings(), 'max_upload_bytes', 1024)
    assert send(b'x' * 1025, admin_headers).status_code == 413


def test_local_disk_failure_returns_controlled_storage_error(client, monkeypatch, tmp_path):
    from app.config import settings
    _, headers = account('admin')
    invalid_directory = tmp_path / 'not-a-directory'
    invalid_directory.write_text('occupied')
    monkeypatch.setattr(settings(), 'upload_dir', invalid_directory)
    blob = io.BytesIO()
    Image.new('RGB', (2, 2)).save(blob, format='PNG')
    response = client.post('/api/uploads/syndromes', headers=headers,
                           files={'file':('x.png', blob.getvalue(), 'image/png')})
    assert response.status_code == 503


def test_import_rejects_missing_answers_instead_of_guessing(client):
    _, headers = account('admin')
    def preview(data):
        return client.post('/api/v1/admin/questions/import-preview',data={'subject_id':'anatomy','year':'BDS-I'},files={'file':('q.csv',data,'text/csv')},headers=headers)
    assert preview(b'Question,A,B,C,D,Answer\nQuestion?,One,Two,Three,Four,B\n').json()[0]['correct_option'] == 1
    assert preview(b'Question,A,B,C,D,Answer\nQuestion?,One,Two,Three,Four,\n').status_code == 422
    assert preview(b'Question,A,B,C,D,Answer\nQuestion?,One,,Three,Four,A\n').status_code == 422


def test_readiness_catalog_and_cors(client):
    assert client.get('/ready').status_code == 200
    assert len(client.get('/api/v1/catalog').json()['subjects']) == 17
    response = client.options('/api/auth/login',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'POST'})
    assert 'access-control-allow-origin' not in response.headers
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_policies WHERE schemaname='public'")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM information_schema.triggers WHERE trigger_schema='public'")).scalar_one() == 0


def test_feature_flags_enforced_by_api(client):
    _, headers = account('admin')
    _, student = account()
    assert client.patch('/api/v1/admin/features/practice_exams',json={'is_visible':False},headers=headers).status_code == 200
    assert client.get('/api/v1/exams',headers=student).status_code == 403
    assert client.get('/api/v1/exams',headers=headers).status_code == 200
    assert client.patch('/api/v1/admin/features/practice_exams',json={'is_visible':True},headers=headers).status_code == 200


def test_question_edits_and_selection_persist(client):
    _, headers = account('admin')
    _, qid = exam(client,headers)
    updated = {'subject_id':'anatomy','year':'BDS-I','text':'Updated question',
               'options':['One','Two','Three','Four'],'correct_option':2,'explanation':'Saved explanation'}
    assert client.patch(f'/api/v1/admin/questions/{qid}',json=updated,headers=headers).status_code == 200
    rows = client.post('/api/v1/admin/question-selection',json={'weightage':{'anatomy':1}},headers=headers).json()
    assert rows[0]['text'] == 'Updated question' and rows[0]['correct_option'] == 2
    assert client.post('/api/v1/admin/question-selection',json={'weightage':{'anatomy':2}},headers=headers).status_code == 409
    assert client.get('/api/v1/admin/question-counts',headers=headers).json()['anatomy'] == 1


def test_content_filters_flowcharts_and_bulk_archive(client):
    _, headers = account('admin')
    _, student = account()
    for subject in ('anatomy','medicine'):
        assert client.post('/api/v1/admin/high-yield',json={'subject_id':subject,'year':'BDS-I','topic_name':subject,
            'question_image_url':'/api/uploads/test.png','answer_image_url':'/api/uploads/test.png'},headers=headers).status_code == 201
    topics = client.get('/api/v1/content/high-yield?subject_id=anatomy',headers=student).json()
    assert len(topics) == 1 and topics[0]['subject_id'] == 'anatomy'
    flowchart = {'question_text':'Question','correct_answer':'Answer','explanation':'Explanation',
                 'generated_flowchart':{'nodes':[],'edges':[]}}
    assert client.post('/api/v1/admin/flowcharts',json=[flowchart,flowchart],headers=headers).status_code == 201
    assert len(client.get('/api/v1/content/flowcharts',headers=student).json()) == 2
    exam(client,headers)
    assert client.post('/api/v1/admin/tests/archive',json={},headers=headers).json()['archived'] == 1
    assert client.get('/api/v1/exams',headers=student).json() == []


def test_exports_formats_audit_and_permissions(client):
    from openpyxl import load_workbook
    _, headers = account('admin')
    _, student = account()
    exam(client,headers)
    assert client.get('/api/v1/admin/exports/questions',headers=student).status_code == 403
    for kind in ('csv','xlsx','json'):
        response = client.get(f'/api/v1/admin/exports/questions?format={kind}',headers=headers)
        assert response.status_code == 200, response.text[:100]
        assert 'attachment' in response.headers['content-disposition']
        if kind == 'xlsx':
            workbook = load_workbook(io.BytesIO(response.content))
            assert workbook.active.max_row == 2
            workbook.close()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.export_audit_events')).scalar_one() == 3


def test_stats_scoped_to_user_and_no_fabricated_rankers(client):
    _, headers = account('admin')
    _, student = account()
    _, other = account()
    exam_id,qid = exam(client,headers)
    assert client.get('/api/v1/leaderboard',headers=student).json() == []
    assert client.post(f'/api/v1/exams/{exam_id}/submit',json={'answers':{qid:1},'request_id':str(uuid.uuid4())},headers=student).status_code == 200
    assert client.get('/api/v1/stats/overview',headers=student).json()['my_completed_exams'] == 1
    assert client.get('/api/v1/stats/overview',headers=other).json()['my_completed_exams'] == 0
    assert client.get('/api/v1/stats/performance',headers=student).json()['averageScore'] == 100
    leaderboard = client.get('/api/v1/leaderboard',headers=student).json()
    assert len(leaderboard) == 1 and leaderboard[0]['score'] == 4
    assert 'email' not in leaderboard[0]


def test_migration_refuses_duplicate_legacy_identity_without_deleting(client):
    # A pre-existing formatted number must be compared using its canonical key.
    account(email='one@example.org', mobile='+919876543210')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO public.app_users (id,email,name,mobile) VALUES (:id,'legacy@example.org','Legacy','98765 43210')"), {'id':uuid.uuid4()})
        connection.execute(text("DELETE FROM public.schema_migrations WHERE version='008_production.sql'"))
    try:
        with pytest.raises(RuntimeError, match='Duplicate legacy'):
            migrate()
    finally:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO public.schema_migrations (version) VALUES ('008_production.sql')"))
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.app_users')).scalar_one() == 2


def test_retention_job_is_bounded_and_preserves_active_codes(client, monkeypatch):
    import sys
    from app.maintenance import main
    with engine.begin() as connection:
        connection.execute(text('''INSERT INTO public.auth_email_challenges (email,purpose,code_digest,expires_at)
            VALUES ('old-one@example.org','register','unused',now()-interval '10 days'),
                   ('old-two@example.org','register','unused',now()-interval '10 days'),
                   ('active@example.org','register','unused',now()+interval '5 minutes')'''))
    monkeypatch.setattr(sys,'argv',['maintenance','--batch-size','1','--retention-days','7'])
    main()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM public.auth_email_challenges')).scalar_one() == 2
        assert connection.execute(text("SELECT count(*) FROM public.auth_email_challenges WHERE email='active@example.org'")).scalar_one() == 1


def test_migration_preserves_invalid_legacy_phones_and_backfills_valid_keys(client):
    invalid_id, valid_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text('''INSERT INTO public.app_users (id,email,name,mobile)
            VALUES (:invalid_id,'legacy-invalid@example.org','Legacy invalid','old invalid value'),
                   (:valid_id,'legacy-valid@example.org','Legacy valid','98765 43210')'''),
            {'invalid_id':invalid_id,'valid_id':valid_id})
        # Simulate the first production backfill while retaining idempotent DDL.
        connection.execute(text("DELETE FROM public.schema_migrations WHERE version='008_production.sql'"))
    migrate()
    with engine.connect() as connection:
        rows = {row['id']:row for row in connection.execute(text('SELECT id,mobile,mobile_e164 FROM public.app_users')).mappings()}
    assert rows[invalid_id]['mobile'] == 'old invalid value'
    assert rows[invalid_id]['mobile_e164'] is None
    assert rows[valid_id]['mobile'] == '98765 43210'
    assert rows[valid_id]['mobile_e164'] == '+919876543210'
    assert client.post('/api/auth/register/request',json=details('new@example.org','old invalid value')).status_code == 422
    assert client.post('/api/auth/register/request',json=details('new@example.org','+91 98765 43210')).status_code == 409
