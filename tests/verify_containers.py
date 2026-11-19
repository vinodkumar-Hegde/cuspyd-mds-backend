"""HTTP smoke test for the isolated frontend and API containers."""
import re
import os
import uuid
import httpx

with httpx.Client(base_url=os.getenv('SMOKE_WEB_URL', 'http://127.0.0.1:3002'), timeout=30) as client:
    index = client.get('/')
    assert index.status_code == 200
    assert 'content-security-policy' in index.headers
    asset = re.search(r'src="([^\"]+\.js)"',index.text).group(1)
    assert client.get(asset).status_code == 200
    catalog = client.get('/api/v1/catalog')
    assert catalog.status_code == 200 and len(catalog.json()['subjects']) == 17
    credentials = {'email':'student@smoke.example.org','password':'Smoke-test-password-123!'}
    login = client.post('/api/auth/login',json=credentials)
    assert login.status_code == 200,login.text
    client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
    assert client.get('/api/auth/me').json()['role'] == 'student'
    assert client.get('/api/v1/admin/users').status_code == 403
    exams = client.get('/api/v1/exams').json()
    exam = next(row for row in exams if row['title'] == 'Browser Smoke Exam')
    questions = client.get(f'/api/v1/exams/{exam["id"]}/questions').json()
    assert questions and 'correct_option' not in questions[0]
    response = client.post(f'/api/v1/exams/{exam["id"]}/submit',json={
        'answers':{questions[0]['id']:1},'request_id':str(uuid.uuid4())})
    assert response.status_code == 200,response.text
    assert response.json()['results']['score'] == 4
    sid = response.json()['session_id']
    assert client.get(f'/api/v1/exams/history/{sid}/result').json()['results']['score'] == 4
    assert client.post('/api/auth/logout').status_code == 204
    client.headers.pop('Authorization')
    registration = {'name':'Smoke Student','email':'STUDENT@smoke.example.org',
                    'password':'Smoke-test-password-123!','mobile':'9876543212'}
    assert client.post('/api/auth/register/request',json=registration).status_code == 409
    registration.update(email='unused@smoke.example.org',mobile='+91 98765 43211')
    assert client.post('/api/auth/register/request',json=registration).status_code == 409
    print('Frontend asset delivery, security headers, API proxy, login, permissions, scoring, result history, logout and duplicate registration passed.')
assert httpx.get(os.getenv('SMOKE_API_URL', 'http://127.0.0.1:18001') + '/ready').json() == {'ok':True}
print('Separate API readiness passed.')
