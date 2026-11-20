"""Canonical API test-data factories, restricted to the disposable database."""
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from app.database import engine
from app.security import issue_token, password_hash

PASSWORD = 'A-real-test-password-123!'


def details(email='student@example.org', mobile='9876543210'):
    return {'name':'Test Student', 'email':email, 'password':PASSWORD,
            'mobile':mobile, 'college':'Test College', 'state':'Test State'}


def register(client, email='student@example.org', mobile='9876543210'):
    response = client.post('/api/auth/register/request', json=details(email, mobile))
    assert response.status_code == 202, response.text
    code = next(code for address, code, purpose in reversed(client.sent) if address == email.lower() and purpose == 'register')
    return client.post('/api/auth/register/verify', json={'email':email, 'code':code})


def account(role='student', email=None, mobile=None):
    uid = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(text('''INSERT INTO public.app_users (id,email,name,password_hash,role,mobile,mobile_e164)
            VALUES (:id,:email,'Test account',:hash,:role,:mobile,:mobile)'''),
            {'id':uid,'email':email or f'{uid}@example.org','hash':password_hash.hash(PASSWORD), 'role':role, 'mobile':mobile})
    return uid, {'Authorization':f'Bearer {issue_token(str(uid))}'}


def exam(client, admin_headers, status='PUBLISHED', image=False):
    question = {'subject_id':'anatomy','year':'BDS-I','text':'A sample question?',
                'options':['A','B','C','D'],'correct_option':1,'explanation':'Explanation',
                'image_url':'https://example.org/question.png' if image else None,
                'image_practice_enabled':image}
    response = client.post('/api/v1/admin/questions', json=[question], headers=admin_headers)
    assert response.status_code == 201, response.text
    question_id = response.json()[0]['id']
    response = client.post('/api/v1/admin/tests', json={'title':'Sample exam','type':'RANKER',
        'status':status, 'questions':[question_id], 'subject_id':'anatomy',
        **({'publish_date':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()} if status == 'SCHEDULED' else {})}, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()['id'], question_id


