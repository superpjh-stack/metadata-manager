"""Restore into a new directory only. Never overwrite live files."""
import argparse,hashlib,json,sqlite3,tempfile,zipfile,shutil
from pathlib import Path
parser=argparse.ArgumentParser(description='백업을 비어 있는 새 디렉터리로 복구합니다.')
parser.add_argument('archive'); parser.add_argument('destination')
args=parser.parse_args()
dest=Path(args.destination).resolve()
if dest.exists():raise SystemExit('복구 대상은 존재하지 않는 새 디렉터리여야 합니다.')
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    with zipfile.ZipFile(args.archive) as z:
        for item in z.infolist():
            p=Path(item.filename)
            if p.is_absolute() or '..' in p.parts:
                raise SystemExit('안전하지 않은 백업 경로입니다.')
        z.extractall(root)
    manifest=json.loads((root/'manifest.json').read_text())
    for name,digest in manifest.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():raise SystemExit('잘못된 파일 경로입니다.')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise SystemExit(f'체크섬 불일치: {name}')
    if 'db.sqlite3' not in manifest:raise SystemExit('DB가 없는 백업입니다.')
    with sqlite3.connect(root/'db.sqlite3') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('DB 무결성 오류입니다.')
    shutil.copytree(root,dest)
print(f'복구 완료: {dest}')
