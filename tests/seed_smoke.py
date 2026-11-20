"""Browser test fixtures. Refuses to run against an application database."""
import uuid
from sqlalchemy import insert
from app.database import Sessions, engine, table
from app.security import password_hash

assert engine.url.database.endswith('_test'), 'A disposable test database is required'
with Sessions.begin() as session:
    for role, mobile in [('admin','+919876543210'), ('student','+919876543211')]:
        user = {'id':uuid.uuid4(),'email':f'{role}@smoke.example.org','name':f'Smoke {role.title()}',
                'mobile':mobile,'role':role,'college':'Smoke Test College','state':'Test'}
        session.execute(insert(table('app_users')).values(**user,mobile_e164=mobile,password_hash=password_hash.hash('Smoke-test-password-123!')))
    qid = session.execute(insert(table('questions')).values(subject_id='anatomy',year='BDS-I',text='Select the second option.',
        options=['First','Second','Third','Fourth'],correct_option=1,explanation='The requested answer is the second option.').returning(table('questions').c.id)).scalar_one()
    session.execute(insert(table('tests')).values(title='Browser Smoke Exam',type='RANKER',status='PUBLISHED',questions=[str(qid)]))
print('Created isolated browser test fixtures.')
