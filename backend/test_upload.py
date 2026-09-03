import requests

# JWT Token for test user
from app.core.security import generate_jwt_token
from app.core.config import app_settings

token = generate_jwt_token(
    subject='test-faculty-001',
    secret=app_settings.secret_key,
    algorithm=app_settings.jwt_algorithm,
    minutes=30
)

session = requests.Session()
session.headers.update({'Authorization': f'Bearer {token}'})

# Get CSRF token
response = session.post('http://localhost:8000/api/v1/auth/csrf')
print('CSRF Response:', response.status_code, response.json())
csrf_token = session.cookies.get('csrf_token')
print('CSRF Token from cookie:', csrf_token)

# Upload with CSRF
file_path = r'E:\Faculty profile portal\backend\test_patent.pdf'
with open(file_path, 'rb') as f:
    files = {'file': ('test_patent.pdf', f, 'application/pdf')}
    headers = {'X-CSRF-Token': csrf_token or ''}
    response = session.post('http://localhost:8000/api/v1/uploads/', headers=headers, files=files)

print('Upload Status:', response.status_code)
print('Upload Response:', response.json())