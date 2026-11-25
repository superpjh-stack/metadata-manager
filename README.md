# 제조데이터 메타데이터 관리 시스템

배포 주소: **https://metadata.187.52.127.215.sslip.io** · [Docker 운영 안내](deploy/README.md)

한 기업·한 사업의 제조데이터 등록, 정의, 점검, Excel 제출자료 생성을 위한 작은 내부 웹 시스템입니다.

Django 서버 렌더링, SQLite, openpyxl을 사용합니다. 실제 측정 데이터는 수집하지 않고 저장 위치와 수집 현황을 담당자가 기록합니다. 공식 제출 서식·적합성 판정·AAS 연계 서버는 포함하지 않습니다.

## 지금 실행하기

GitHub에서 처음 내려받았다면 아래 **새로운 환경에 설치** 절차를 먼저 진행하세요. `.venv`, DB, 계정 정보, 업로드 파일은 저장소에 포함하지 않습니다. 로컬 설치와 예시 데이터 준비를 마친 환경에서는 다음 방법으로 실행합니다.

1. **`시작.command`를 실행**합니다. 또는 아래 명령을 터미널에서 실행합니다.
2. 브라우저에서 **http://127.0.0.1:8000** 을 엽니다.
3. `.local-demo-login` 파일에 저장된 무작위 생성 계정으로 로그인합니다.
4. 종료하려면 서버 터미널에서 Control+C를 누릅니다.

```sh
cd /path/to/metadata-manager
./시작.command
```

계정 파일은 숨김 파일이며 파일 소유자만 읽을 수 있습니다. Finder에서 Command+Shift+. 로 숨김 파일을 표시하거나 아래 명령으로 확인합니다.

```sh
cat .local-demo-login
```

예시 환경에는 3개의 가상 데이터셋, 입력 완료·미입력·보완 필요 상태, 제출본, 검증용 가상 증빙이 있습니다. 실제 업무 자료와 분리해 사용하세요. 계정의 비밀번호는 소스에 하드코딩되어 있지 않습니다.

## 새로운 환경에 설치

검증 환경: Python 3.14.7, Django 5.2.19, openpyxl 3.1.5.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py create_user manager --manager
.venv/bin/python manage.py create_user reader
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

비밀번호는 대화형으로 입력합니다. `manager`는 등록·수정·점검·제출·설정을 수행하고, `reader`는 조회·첨부 다운로드·기존 제출본 다운로드만 할 수 있습니다. 계정 관리는 명령행으로 제한했습니다.

기존 계정의 비밀번호 변경:

```sh
.venv/bin/python manage.py changepassword manager
```

신규 예시 환경 준비는 명시적으로 실행합니다. 운영 DB에는 샘플을 주입하지 않습니다.

```sh
DB_PATH=demo.sqlite3 MEDIA_ROOT=demo-media .venv/bin/python manage.py migrate
DB_PATH=demo.sqlite3 MEDIA_ROOT=demo-media .venv/bin/python manage.py seed_demo
```

`seed_demo`는 이름이 `demo.sqlite3`인 빈 DB에서만 실행됩니다. 기존 계정이나 데이터가 있으면 중단합니다.

## 업무 흐름

1. 사업·항목 설정에서 기업명, 사업명, 기간을 입력합니다.
2. 데이터 목록에서 데이터셋을 등록합니다. 데이터명만으로 임시 저장할 수 있습니다.
3. 컬럼 정의에 컬럼명·의미·자료형·단위 등을 작성합니다. 별표는 입력 완료에 필요한 항목입니다.
4. 상세 화면에서 점검 의견, 조치 내용과 증빙을 관리합니다.
5. 점검·제출에서 누락 및 보완사항을 확인하고 제출 대상을 선택합니다.
6. 생성된 Excel을 다운로드합니다. 제출 당시의 데이터·항목 정의·파일이 DB에 함께 보존됩니다.

수집 상태, 입력 상태, 점검 상태는 서로 다른 값입니다. 입력·점검 완료는 정부 승인이나 공식 기준 충족을 뜻하지 않습니다.

### Excel 가져오기

화면에서 표준 양식을 다운로드합니다. `데이터셋` 시트에 임시 연결키와 기본정보를 입력하고, `컬럼 정의` 시트에 같은 연결키로 컬럼을 연결합니다.

- XLSX 파일, 최대 10MB, 시트당 5,000행.
- 표준 헤더와 시트명을 유지합니다.
- 컬럼 자료형: text, integer, decimal, boolean, date, datetime.
- 필수값: 예/아니오 또는 true/false. 순서: 0 이상의 정수.
- 날짜: YYYY-MM-DD 또는 Excel 날짜 셀.
- 수식은 지원하지 않습니다. 값을 입력합니다.
- 오류가 있으면 전체 저장을 보류합니다. 시트·행·항목 오류를 확인해 수정합니다.
- 필수 메타데이터 누락은 경고와 함께 미완성 상태로 가져올 수 있습니다.
- 미리보기는 1시간 동안 유효하고 한 번만 확정할 수 있습니다.
- 기존 데이터와 이름이 같아도 새 데이터로 등록됩니다. 자동 덮어쓰기는 없습니다.
- 추가 항목 값은 가져오기 이후 상세 편집에서 입력합니다.

표준 양식은 `outputs/metadata_import_template.xlsx`, 가상 예시 제출본은 `outputs/sample_submission.xlsx`에도 있습니다.

### 추가 항목과 변경 이력

추가 항목은 한 줄·여러 줄 텍스트와 필수·활성 여부만 지원합니다. 항목 키는 생성 후 바꿀 수 없습니다. 비활성화해도 기존 값과 과거 제출본은 유지됩니다.

데이터·컬럼·점검·항목 설정의 변경 전후 값이 기록됩니다. 컬럼 삭제도 이력에 남습니다. 데이터셋 자체의 삭제 기능은 제공하지 않습니다. 데이터 상세에서 해당 데이터의 최근 30개 이력을 펼쳐 볼 수 있습니다. 사업·추가 항목 설정 이력은 DB에 보관합니다.

## 백업과 복구

제출본은 DB 안에 저장되며, 증빙은 MEDIA_ROOT에 저장됩니다. 두 가지를 함께 백업해야 합니다.

**백업 동안 앱의 쓰기 작업을 중지하세요.** 로컬 서버를 종료한 상태에서 실행하면 DB와 첨부파일 사이의 일관성을 유지할 수 있습니다.

업무용:

```sh
.venv/bin/python manage.py backup_data --output backups
```

예시용:

```sh
DB_PATH=demo.sqlite3 MEDIA_ROOT=demo-media .venv/bin/python manage.py backup_data --output backups
```

백업 ZIP에는 SQLite 백업본, 증빙 파일, SHA-256 체크섬 목록이 들어갑니다. 계정과 업무 데이터가 포함되므로 백업은 소유자 전용 권한으로 생성됩니다. 운영 SECRET_KEY는 별도로 보관하세요.

복구는 기존 데이터를 덮어쓰지 않고 **존재하지 않는 새 디렉터리**에 수행합니다.

```sh
.venv/bin/python scripts/restore_backup.py backups/metadata-생성시각.zip restored-data
DB_PATH="$PWD/restored-data/db.sqlite3" MEDIA_ROOT="$PWD/restored-data/media" .venv/bin/python manage.py check
DB_PATH="$PWD/restored-data/db.sqlite3" MEDIA_ROOT="$PWD/restored-data/media" .venv/bin/python manage.py runserver 127.0.0.1:8000
```

복구 프로그램은 파일 체크섬 및 SQLite 무결성을 검증합니다. 복구 후 데이터 목록, 증빙, 제출본 다운로드를 확인하세요.

정기 백업 예시: 매일 02:00을 앱 쓰기가 중지된 유지보수 시간으로 정한 뒤 cron에 다음 작업을 등록할 수 있습니다. 실제 스케줄러 등록은 하지 않았습니다. 운영 서버를 계속 가동해야 한다면 서비스 관리자의 정지→백업→시작 절차로 연결해야 합니다.

```cron
0 2 * * * cd "/absolute/path/project" && .venv/bin/python manage.py backup_data --output backups >> backups/schedule.log 2>&1
```

로그 경로를 위해 먼저 `backups` 디렉터리를 생성하세요. 보존기간에 따른 자동 백업 삭제는 구현하지 않았습니다.

## 검증

```sh
.venv/bin/python manage.py test registry
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```

가상 예시 서버가 실행 중일 때만 HTTP 흐름 검증을 수행할 수 있습니다. 이 검사는 예시 DB에 증빙과 제출본을 추가합니다.

```sh
.venv/bin/python scripts/http_smoke.py
```

서버를 중지한 뒤 가상 예시 DB와 증빙 파일의 백업·복구 검증:

```sh
.venv/bin/python scripts/verify_backup.py
```

상세 결과는 `docs/verification.md`를 참조하세요. UI 개선 후 네이티브 Chrome 앱에서 개요·목록의 넓은/좁은 화면 및 접이식 메뉴 동작을 확인했습니다. 전체 화면·기기에 대한 시각 검증은 수행하지 않았습니다. Excel은 다시 읽어 내용과 서식을 검사했으나 Excel 앱에서 시각 검증하지 못했습니다.

## 운영 범위

Hostinger VPS에 Docker·Gunicorn·HTTPS로 배포했습니다. Docker 구성과 운영 절차는 `deploy/README.md`를 참조하세요. 정기 백업 스케줄은 아직 등록하지 않았습니다. `runserver`는 로컬 확인용입니다. 실제 서비스 배포 시 WSGI 서버, HTTPS, 정적 파일 제공, 백업 스케줄을 설정해야 합니다.

DEBUG=0일 때 SECRET_KEY를 반드시 환경변수로 지정해야 하며 세션·CSRF 쿠키는 HTTPS 전용입니다. `.env.example`은 참고 파일이며 자동으로 읽지 않습니다. 코드에 `.local-secret`, `.local-demo-login`, DB, media, backups를 커밋하지 않도록 `.gitignore`에 등록했습니다.

공식 메타데이터 세부항목과 제출 양식이 제공되면 현재 기본항목 및 추가 항목을 해당 요구와 대조하여 조정해야 합니다.

## 담당자와 로그인 계정 연결

1. 관리자로 로그인해 **사업·항목 설정 → 담당자 계정 관리**를 엽니다.
2. 필요한 계정이 없으면 **계정 등록**에서 로그인 ID, 이름, 비밀번호를 입력합니다. 신규 계정은 일반 담당자로 생성됩니다.
3. **데이터 목록 → 데이터 상세 → 담당 계정 변경**에서 실제 계정을 선택하고 저장합니다.
4. 목록의 담당 계정 필터에서 **내 담당 데이터**, **계정 미연결**, **비활성 담당 계정**, 특정 계정을 선택할 수 있습니다.

기존 담당자 표기명은 보존됩니다. 표기명이 비어 있으면 선택한 계정 이름으로 채웁니다. 이름이 같다는 이유로 자동 연결하지 않으며 Excel 가져오기도 계정 미연결로 등록합니다. 담당 계정의 변경·해제는 변경 이력에 기록됩니다. 새 제출본의 데이터 목록에는 계정 ID와 이름이 추가되고 과거 제출본은 변하지 않습니다.

일반 담당자는 배정된 데이터의 현황 확인 및 증빙 첨부, 배정된 보완 조치의 처리·검토 요청이 가능합니다. 데이터 정의 수정, 담당·기한 지정, 최종 완료 확인은 관리자 전용입니다. 비활성 계정에 신규 배정할 수 없으며 이미 연결된 비활성 계정은 경고로 표시해 재배정할 수 있습니다. 연결된 계정은 DB에서 삭제가 보호됩니다. 계정 비활성화·비밀번호 재설정은 시스템 관리자에게 요청하세요.


## 내 업무 · 현황 확인 · 보완 조치

- 로그인 후 **내 업무**가 열립니다. 관리자는 전체 업무와 내 담당을 전환할 수 있고, 담당자는 본인에게 배정된 업무만 봅니다.
- **데이터 수정**에서 확인 주기(7/30/90일 또는 수시)와 최초 기한을 설정합니다. 최초 기한이 없으면 등록일을 사용합니다. 기존 데이터에는 기본 30일이 적용됩니다.
- **현황 확인**에서 수집 상태, 위치·담당자, 이용조건을 직접 확인하고 ‘변경 없음’을 저장하면 다음 확인 기한이 계산됩니다. 확인 기록은 데이터 수정일과 별도로 보관됩니다. ‘변경 필요’는 메모가 필수이며 업무를 완료하지 않습니다. 관리자가 데이터를 수정한 후 재확인하세요.
- **점검 및 조치**에서 관리자가 조치 담당자와 기한을 지정합니다. 담당자는 ‘보완 중’으로 저장하거나 ‘검토 대기’로 제출하고, 관리자가 조치 내용과 완료일을 확인해 ‘보완 완료’로 저장합니다. 재작업이 필요하면 ‘보완 중’으로 돌립니다.
- 미지정 담당·기한은 자동 추정하지 않고 화면에 표시합니다. 기한 경과와 검토 대기를 우선 표시하며, 정기 확인은 7일 이내 도래 항목까지 표시합니다. 이메일·메신저 자동 알림은 포함하지 않습니다.
- 새 제출 Excel의 **현황 확인** 시트와 **점검 및 조치** 시트에 이력·담당·기한·완료 확인 정보가 포함됩니다. 기존 제출본은 보존됩니다.
