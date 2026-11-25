import uuid
from pathlib import Path
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

COLLECTION = [(x,x) for x in ['준비 중','수집 중','일시 중단','종료']]
SHARING = [(x,x) for x in ['가능','조건부 가능','불가','미확인']]
REQUIRED = ['name','description','owner','source','method','frequency','location','format','collection_status','rights_owner','manager','purpose','access','sharing','conditions']

def private_path(instance, filename):
    return f'evidence/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'

class Project(models.Model):
    company = models.CharField('기업명',max_length=150,blank=True)
    name = models.CharField('사업명',max_length=200,blank=True)
    start = models.DateField('사업 시작일',null=True,blank=True)
    end = models.DateField('사업 종료일',null=True,blank=True)
    def clean(self):
        if self.start and self.end and self.start > self.end:
            raise ValidationError({'end':'종료일은 시작일 이후여야 합니다.'})

class Dataset(models.Model):
    name = models.CharField('데이터명',max_length=200)
    description = models.TextField('데이터 설명',blank=True)
    process = models.CharField('관련 공정',max_length=150,blank=True)
    equipment = models.CharField('관련 설비',max_length=150,blank=True)
    owner = models.CharField('담당자',max_length=100,blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='담당 계정',
                                 on_delete=models.PROTECT, related_name='assigned_datasets',
                                 null=True, blank=True)
    source = models.CharField('원천 시스템 또는 장비',max_length=200,blank=True)
    method = models.CharField('수집방법',max_length=150,blank=True)
    frequency = models.CharField('수집주기',max_length=100,blank=True)
    started_on = models.DateField('수집 시작일',null=True,blank=True)
    location = models.CharField('저장 위치',max_length=500,blank=True,help_text='경로 또는 시스템명만 입력하세요. 비밀번호·토큰은 입력하지 않습니다.')
    format = models.CharField('파일 형식 또는 DB 테이블명',max_length=200,blank=True)
    retention = models.CharField('보관기간',max_length=100,blank=True)
    collection_status = models.CharField('수집 상태',max_length=20,choices=COLLECTION,blank=True)
    rights_owner = models.CharField('소유 주체',max_length=150,blank=True)
    manager = models.CharField('관리 주체',max_length=150,blank=True)
    purpose = models.TextField('사용 목적',blank=True)
    access = models.CharField('접근 대상',max_length=200,blank=True)
    sharing = models.CharField('외부 제공 여부',max_length=30,choices=SHARING,blank=True)
    conditions = models.TextField('이용조건',blank=True)
    extras = models.JSONField(default=dict,blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+',null=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+',null=True)
    class Meta:
        ordering = ['-updated_at']
    @property
    def code(self):
        return f'MD-{self.pk:05d}' if self.pk else '신규'
    @property
    def assignee_label(self):
        if not self.assignee_id:
            return '계정 미연결'
        name = self.assignee.get_full_name().strip()
        return f'{name} ({self.assignee.username})' if name else self.assignee.username
    def assignee_snapshot(self):
        if not self.assignee_id:
            return None
        return {'id':self.assignee_id, 'username':self.assignee.username,
                'name':self.assignee.get_full_name().strip(), 'active':self.assignee.is_active}
    def missing(self, definitions=None):
        missing = [str(self._meta.get_field(k).verbose_name) for k in REQUIRED if not str(getattr(self,k) or '').strip()]
        if definitions is None:
            definitions = ExtraField.objects.filter(active=True,required=True)
        missing += [f.label for f in definitions if f.active and f.required and not str(self.extras.get(f.key,'')).strip()]
        return missing
    @property
    def input_status(self):
        return '미입력 있음' if self.missing() else '입력 완료'
    @property
    def review_status(self):
        checks = list(self.checks.all())
        if not checks:
            return '미점검'
        return '보완 필요' if any(c.needs_action and c.status != '보완 완료' for c in checks) else '점검 완료'

class Column(models.Model):
    dataset = models.ForeignKey(Dataset,on_delete=models.CASCADE,related_name='columns')
    name = models.CharField('컬럼명',max_length=100)
    meaning = models.CharField('의미',max_length=250)
    dtype = models.CharField('자료형',max_length=30,choices=[(x,x) for x in ['text','integer','decimal','boolean','date','datetime']])
    unit = models.CharField('단위',max_length=50,blank=True)
    required = models.BooleanField('필수값',default=False)
    notes = models.CharField('비고',max_length=250,blank=True)
    order = models.PositiveIntegerField('순서',default=0)
    class Meta:
        ordering = ['order','id']
        constraints = [models.UniqueConstraint(fields=['dataset','name'],name='unique_dataset_column')]

class Check(models.Model):
    dataset = models.ForeignKey(Dataset,on_delete=models.CASCADE,related_name='checks')
    date = models.DateField('점검일',default=timezone.localdate)
    inspector = models.CharField('점검자 이름',max_length=100)
    opinion = models.TextField('점검 의견')
    needs_action = models.BooleanField('보완 필요',default=False)
    action = models.TextField('조치 내용',blank=True)
    status = models.CharField('보완 상태',max_length=20,choices=[(x,x) for x in ['보완 필요','보완 중','보완 완료']],default='보완 필요')
    completed_on = models.DateField('조치 완료일',null=True,blank=True)
    class Meta:
        ordering = ['-date','-id']
    def clean(self):
        if self.needs_action and self.status == '보완 완료':
            if not self.action.strip():
                raise ValidationError({'action':'보완 완료 시 조치 내용을 입력하세요.'})
            if not self.completed_on:
                raise ValidationError({'completed_on':'조치 완료일을 입력하세요.'})
            if self.completed_on < self.date:
                raise ValidationError({'completed_on':'완료일은 점검일 이후여야 합니다.'})
        elif self.completed_on:
            raise ValidationError({'completed_on':'완료일은 보완 완료 상태에서만 입력하세요.'})

class ExtraField(models.Model):
    key = models.SlugField('항목 키',unique=True,help_text='영문·숫자·밑줄. 생성 후 변경할 수 없습니다.')
    label = models.CharField('항목명',max_length=150)
    description = models.CharField('설명',max_length=300,blank=True)
    multiline = models.BooleanField('여러 줄 입력',default=False)
    required = models.BooleanField('필수 여부',default=False)
    active = models.BooleanField('활성 여부',default=True)
    order = models.PositiveIntegerField('표시 순서',default=0)
    class Meta:
        ordering = ['order','id']

class Attachment(models.Model):
    dataset = models.ForeignKey(Dataset,on_delete=models.CASCADE,related_name='attachments')
    file = models.FileField(upload_to=private_path)
    original_name = models.CharField(max_length=255)
    description = models.CharField('설명',max_length=250,blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

class Audit(models.Model):
    dataset = models.ForeignKey(Dataset,on_delete=models.PROTECT,null=True,related_name='audits')
    target = models.CharField(max_length=200)
    operation = models.CharField(max_length=30)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    at = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(default=dict)
    class Meta:
        ordering = ['-at']

class Submission(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    created_at = models.DateTimeField(default=timezone.now,editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    snapshot = models.JSONField()
    workbook = models.BinaryField()
    class Meta:
        ordering = ['-created_at']

class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    consumed = models.BooleanField(default=False)
