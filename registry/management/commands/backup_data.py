import hashlib,json,sqlite3,shutil,tempfile,zipfile
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError

class Command(BaseCommand):
    help='DB와 증빙 파일을 ZIP으로 백업합니다. 실행 전 앱 쓰기 작업을 중지하세요.'
    def add_arguments(self,parser):
        parser.add_argument('--output',default='backups')
    def handle(self,*args,**opts):
        output=Path(opts['output']).resolve(); output.mkdir(parents=True,exist_ok=True)
        target=output/f'metadata-{datetime.now():%Y%m%d-%H%M%S-%f}.zip'
        source=Path(settings.DATABASES['default']['NAME'])
        if not source.is_file():
            raise CommandError('DB 파일이 없습니다.')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with sqlite3.connect(source) as src,sqlite3.connect(root/'db.sqlite3') as dest:
                src.backup(dest)
            media=Path(settings.MEDIA_ROOT)
            if media.exists():
                shutil.copytree(media,root/'media')
            manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                for p in root.rglob('*'):
                    if p.is_file():z.write(p,p.relative_to(root))
        target.chmod(0o600)
        self.stdout.write(str(target))
