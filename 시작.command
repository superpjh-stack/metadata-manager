#!/bin/zsh
set -e
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
  print '먼저 README.md의 설치 절차를 실행하세요.'
  exit 1
fi
if [[ ! -f demo.sqlite3 ]]; then
  print '데모 DB가 없습니다. README.md의 예시 데이터 준비 절차를 실행하세요.'
  exit 1
fi
print '제조데이터 관리대장 — 가상 예시 환경'
print '브라우저 접속: http://127.0.0.1:8000'
print '로그인 계정: 이 폴더의 .local-demo-login 파일'
print '종료: 이 창에서 Control+C'
DB_PATH="$project_dir/demo.sqlite3" MEDIA_ROOT="$project_dir/demo-media" exec .venv/bin/python manage.py runserver 127.0.0.1:8000
