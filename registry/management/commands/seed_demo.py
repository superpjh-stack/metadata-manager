import secrets
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from registry.models import Dataset,Column,Check,Project
from registry.services import audit,values,create_submission,import_template

class Command(BaseCommand):
    help='빈 demo.sqlite3 전용 DB에 가상 예시 3건을 생성합니다. 운영 DB에서 실행할 수 없습니다.'
    @transaction.atomic
    def handle(self,*args,**opts):
        if Path(settings.DATABASES['default']['NAME']).name!='demo.sqlite3':
            raise CommandError('DB_PATH를 demo.sqlite3로 지정해야 합니다.')
        if Dataset.objects.exists() or get_user_model().objects.exists():
            raise CommandError('비어 있는 데모 DB에서만 실행할 수 있습니다.')
        password=secrets.token_urlsafe(15)
        user=get_user_model().objects.create_user('demo_admin',password=password,is_staff=True)
        Project.objects.create(pk=1,company='예시 제조기업 (가상)',name='제조데이터 관리 시범사업 (예시)')
        common=dict(description='가상의 사용 흐름을 보여주기 위한 예시 데이터입니다.',process='가공',equipment='1호기',owner='예시 담당자',source='예시 MES',method='CSV 정기 저장',frequency='1일',location='/sample/manufacturing/',format='CSV',retention='1년',collection_status='수집 중',rights_owner='예시 제조기업',manager='생산관리팀 (예시)',purpose='내부 공정 분석 예시',access='내부 담당자',sharing='불가',conditions='가상 예시이며 실제 사업 제출에 사용할 수 없습니다.',created_by=user,updated_by=user)
        a=Dataset.objects.create(name='[예시] 1호기 온도 이력',**common)
        Column.objects.create(dataset=a,name='temperature',meaning='온도',dtype='decimal',unit='℃',required=True)
        Column.objects.create(dataset=a,name='measured_at',meaning='측정 시각',dtype='datetime',required=True,order=1)
        Check.objects.create(dataset=a,inspector='가상 점검자',opinion='점검 완료 상태를 보여주는 가상 기록입니다.')
        b=Dataset.objects.create(name='[예시] 제품 품질검사 결과',description='일부 항목이 비어 있는 가상 데이터입니다.',process='품질검사',owner='예시 담당자',created_by=user,updated_by=user)
        Column.objects.create(dataset=b,name='result',meaning='검사 결과',dtype='text')
        c=Dataset.objects.create(name='[예시] 일일 생산실적',**{**common,'process':'생산','equipment':'생산라인 A'})
        Column.objects.create(dataset=c,name='quantity',meaning='생산 수량',dtype='integer',unit='개',required=True)
        Check.objects.create(dataset=c,inspector='가상 점검자',opinion='보관기간의 근거를 첨부하는 보완 절차 예시입니다.',needs_action=True)
        for obj in [a,b,c]:
            audit(user,obj.code,{},values(obj),obj,'예시 생성')
        submission=create_submission([a,b,c],user)
        out=settings.BASE_DIR/'outputs'; out.mkdir(exist_ok=True)
        (out/'metadata_import_template.xlsx').write_bytes(import_template())
        (out/'sample_submission.xlsx').write_bytes(bytes(submission.workbook))
        login=settings.BASE_DIR/'.local-demo-login'
        login.write_text(f'로컬 가상 데이터 전용 계정\n아이디: demo_admin\n비밀번호: {password}\n',encoding='utf-8')
        login.chmod(0o600)
        self.stdout.write(self.style.SUCCESS('예시 3건과 제출본을 생성했습니다. 계정 정보: .local-demo-login (소유자 전용)'))
