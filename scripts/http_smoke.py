"""Local demo-only HTTP workflow verification, no browser automation."""
import http.cookiejar,re,urllib.request,urllib.parse
from pathlib import Path
base='http://127.0.0.1:8000'
jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def get(path):
    with client.open(base+path) as response:
        assert response.status==200
        return response.read().decode()
def post(path,payload):
    token=next(c.value for c in jar if c.name=='csrftoken')
    request=urllib.request.Request(base+path,data=urllib.parse.urlencode({'csrfmiddlewaretoken':token,**payload}).encode(),headers={'Referer':base+path})
    with client.open(request) as response:
        assert response.status==200
        return response.read().decode()
get('/accounts/login/')
login_text=Path('.local-demo-login').read_text()
username=login_text.split('아이디: ')[1].splitlines()[0].strip()
password=login_text.split('비밀번호: ')[1].strip()
html=post('/accounts/login/',{'username':username,'password':password})
assert '데이터 관리대장' in html and username in html
for path,expected in [('/datasets/1/','temperature'),('/datasets/1/edit/','columns-TOTAL_FORMS'),('/submissions/','보관된 제출본'),('/settings/','예시 제조기업'),('/import/','표준 양식')]:
    assert expected in get(path),(path,expected)
# A real multipart POST for a labeled demo evidence file.
token=next(c.value for c in jar if c.name=='csrftoken')
boundary='MetadataSmokeBoundary'
body=(f'--{boundary}\r\nContent-Disposition: form-data; name="csrfmiddlewaretoken"\r\n\r\n{token}\r\n'
      f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\n가상 예시 증빙 (HTTP 검증)\r\n'
      f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample-evidence.csv"\r\nContent-Type: text/csv\r\n\r\nsample,value\nexample,1\n\r\n--{boundary}--\r\n').encode()
req=urllib.request.Request(base+'/datasets/1/upload/',data=body,headers={'Content-Type':f'multipart/form-data; boundary={boundary}','Referer':base+'/datasets/1/'})
with client.open(req) as response:
    html=response.read().decode();assert 'sample-evidence.csv' in html
url=re.search(r'href="(/attachments/\d+/)"',html).group(1)
with client.open(base+url) as response:
    assert b'example,1' in response.read()
html=post('/submissions/create/',{'datasets':'1'})
assert '제출본을 생성했습니다.' in html
url=re.search(r'href="(/submissions/[^/]+/download/)"',html).group(1)
with client.open(base+url) as response:
    assert response.read().startswith(b'PK')
print('PASS: actual HTTP login + 5 pages + authenticated evidence upload/download + submission creation/download (CSRF enabled).')
