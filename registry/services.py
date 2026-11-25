import json
from datetime import date, datetime
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from .models import Dataset, Column, Check, ExtraField, Project, Audit, Submission
from .forms import DatasetForm, DATA_FIELDS

HEADERS = ['연결키'] + [str(Dataset._meta.get_field(k).verbose_name) for k in DATA_FIELDS]
COLUMN_FIELDS = ['name','meaning','dtype','unit','required','notes','order']
COLUMN_HEADERS = ['연결키'] + [str(Column._meta.get_field(k).verbose_name) for k in COLUMN_FIELDS]

def jsonable(value):
    return json.loads(json.dumps(value,cls=DjangoJSONEncoder,ensure_ascii=False))

def values(obj, fields=None):
    return jsonable(model_to_dict(obj,fields=fields))

def audit(actor,target,before,after,dataset=None,operation='수정'):
    changes = {k:{'before':before.get(k),'after':after.get(k)} for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    if changes:
        Audit.objects.create(actor=actor,target=target,dataset=dataset,operation=operation,changes=changes)

def sheet(wb,title,headers,rows):
    ws = wb.create_sheet(title)
    for row in [headers]+list(rows):
        ws.append(row)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value,str):
                cell.data_type = 's'  # Preserve literal input, including leading '='.
            cell.alignment = Alignment(vertical='top',wrap_text=True)
            if isinstance(cell.value,(date,datetime)):
                cell.number_format = 'yyyy-mm-dd'
    for cell in ws[1]:
        cell.font = Font(name='맑은 고딕',bold=True,color='FFFFFF',size=11)
        cell.fill = PatternFill('solid',fgColor='163B44')
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 30
    for col in ws.columns:
        width = min(48,max(18,max(len(str(c.value or ''))*1.7 for c in col[:30])+2))
        ws.column_dimensions[col[0].column_letter].width = width
    for row in ws.iter_rows(min_row=2):
        ws.row_dimensions[row[0].row].height = min(180,max(34,max((len(str(c.value or ''))//24+1)*18 for c in row)))
        for cell in row:
            cell.font = Font(name='맑은 고딕',size=11)
    return ws

def workbook_bytes(wb):
    out = BytesIO()
    wb.save(out)
    return out.getvalue()

def import_template():
    wb = Workbook(); wb.remove(wb.active)
    sheet(wb,'데이터셋',HEADERS,[])
    sheet(wb,'컬럼 정의',COLUMN_HEADERS,[])
    return workbook_bytes(wb)

def parse_import(upload):
    errors, records, warnings = [], [], []
    if upload.size > 10*1024*1024 or not upload.name.lower().endswith('.xlsx'):
        return [],['XLSX 파일만 가능하며 최대 10MB입니다.'],[]
    try:
        with ZipFile(upload) as z:
            if sum(i.file_size for i in z.infolist()) > 40*1024*1024:
                raise ValueError('압축 해제 크기가 너무 큽니다.')
        upload.seek(0)
        wb = load_workbook(upload,read_only=True,data_only=False)
    except Exception:
        return [],['올바른 XLSX 파일이 아니거나 허용 크기를 초과했습니다.'],[]
    by_key = {}
    try:
        for title,headers in [('데이터셋',HEADERS),('컬럼 정의',COLUMN_HEADERS)]:
            if title not in wb.sheetnames:
                errors.append(f'{title}: 필수 시트가 없습니다.')
                continue
            ws = wb[title]
            if ws.max_row > 5001 or ws.max_column > len(headers):
                errors.append(f'{title}: 최대 5,000행이며 표준 양식의 열만 허용합니다.')
                continue
            rows = ws.iter_rows(values_only=False)
            first = next(rows,[])
            if [c.value for c in first] != headers:
                errors.append(f'{title} 1행: 표준 양식의 헤더와 일치하지 않습니다.')
                continue
            for number,cells in enumerate(rows,2):
                row = [c.value for c in cells]
                if not any(v is not None for v in row):
                    continue
                if any(c.data_type == 'f' for c in cells):
                    errors.append(f'{title} {number}행: 수식 대신 값을 입력하세요.')
                    continue
                row += [None] * (len(headers)-len(row))
                key = str(row[0] or '').strip()
                if not key:
                    errors.append(f'{title} {number}행 연결키: 필수입니다.'); continue
                if title == '데이터셋':
                    if key in by_key:
                        errors.append(f'{title} {number}행 연결키: 중복입니다.'); continue
                    data = dict(zip(DATA_FIELDS,row[1:]))
                    if isinstance(data['started_on'],datetime):
                        data['started_on'] = data['started_on'].date()
                    form = DatasetForm({k:('' if v is None else v) for k,v in data.items()})
                    if not form.is_valid():
                        for field,issues in form.errors.items():
                            errors.append(f'{title} {number}행 {form.fields[field].label}: {" / ".join(issues)}')
                        continue
                    obj = form.save(commit=False)
                    record = {'key':key,'data':values(obj,DATA_FIELDS),'columns':[]}
                    by_key[key] = record; records.append(record)
                    missing = obj.missing()
                    if missing:
                        warnings.append(f'{number}행 {obj.name}: 미입력 — {", ".join(missing)}')
                    if Dataset.objects.filter(name=obj.name,archived=False).exists():
                        warnings.append(f'{number}행 {obj.name}: 같은 이름이 이미 있습니다. 새 데이터로 등록됩니다.')
                else:
                    if key not in by_key:
                        errors.append(f'{title} {number}행 연결키: 유효한 데이터셋이 없습니다.'); continue
                    data = dict(zip(COLUMN_FIELDS,row[1:]))
                    raw_required = str(data['required'] if data['required'] is not None else '').strip().lower()
                    if raw_required not in ['','true','false','1','0','예','아니오']:
                        errors.append(f'{title} {number}행 필수값: 예/아니오 또는 true/false를 입력하세요.'); continue
                    data['required'] = raw_required in ['true','1','예']
                    data['order'] = data['order'] if data['order'] is not None else 0
                    data = {k:('' if v is None else v.strip() if isinstance(v,str) else v) for k,v in data.items()}
                    col = Column(**data)
                    try:
                        col.full_clean(exclude=['dataset'],validate_unique=False,validate_constraints=False)
                    except ValidationError as exc:
                        errors.append(f'{title} {number}행: {exc}'); continue
                    if any(c['name'] == col.name for c in by_key[key]['columns']):
                        errors.append(f'{title} {number}행 컬럼명: 같은 데이터셋에서 중복입니다.'); continue
                    by_key[key]['columns'].append(values(col,COLUMN_FIELDS))
        if not records and not errors:
            errors.append('데이터셋 시트: 가져올 데이터가 없습니다.')
    finally:
        wb.close()
    return records,errors,warnings

@transaction.atomic
def save_import(records,user):
    created = []
    for record in records:
        form = DatasetForm(record['data'])
        if not form.is_valid():
            raise ValidationError('확정 전 데이터 검증에 실패했습니다. 다시 업로드하세요.')
        obj = form.save(commit=False)
        obj.created_by = obj.updated_by = user
        obj.save()
        for data in record['columns']:
            col = Column(dataset=obj,**data)
            col.full_clean(); col.save()
        audit(user,obj.code,{},values(obj),obj,'가져오기')
        created.append(obj)
    return created

@transaction.atomic
def create_submission(datasets,user):
    datasets = list(datasets)
    if not datasets:
        raise ValidationError('제출 대상을 선택하세요.')
    definitions = list(ExtraField.objects.all())
    project = Project.objects.first()
    snapshot = {'project':values(project) if project else {},'definitions':[values(f) for f in definitions],'datasets':[]}
    for obj in datasets:
        snapshot['datasets'].append({'code':obj.code,'assignee':obj.assignee_snapshot(),'data':values(obj,DATA_FIELDS+['extras']),'missing':obj.missing(definitions),'review_status':obj.review_status,'columns':[values(c,COLUMN_FIELDS) for c in obj.columns.all()],'checks':[values(c,['date','inspector','opinion','needs_action','action','status','completed_on']) for c in obj.checks.all()]})
    result = Submission(created_by=user,snapshot=snapshot)
    wb = Workbook(); wb.remove(wb.active)
    p = snapshot['project']
    sheet(wb,'제출정보',['항목','내용'],[['기업명',p.get('company','')],['사업명',p.get('name','')],['사업 시작일',project.start if project else None],['사업 종료일',project.end if project else None],['제출본 ID',str(result.id)],['생성일',timezone.localtime(result.created_at).replace(tzinfo=None)],['생성자',user.username],['데이터셋 수',len(datasets)],['안내','일반 제출 참고용입니다. 공식 확정 양식 및 적합성 판정이 아닙니다. 수집 상태는 담당자의 기록입니다.']])
    rows = snapshot['datasets']
    sheet(wb,'데이터 목록',['관리번호','데이터명','공정','설비','담당자','수집 상태','입력 상태','점검 상태','담당 계정','담당 계정 이름'],[[r['code'],r['data']['name'],r['data']['process'],r['data']['equipment'],r['data']['owner'],r['data']['collection_status'],'미입력 있음' if r['missing'] else '입력 완료',r['review_status'],(r['assignee'] or {}).get('username',''),(r['assignee'] or {}).get('name','')] for r in rows])
    sheet(wb,'데이터 정의',['관리번호']+HEADERS[1:],[[r['code']]+[date.fromisoformat(r['data'][k]) if k=='started_on' and r['data'][k] else r['data'][k] for k in DATA_FIELDS] for r in rows])
    sheet(wb,'컬럼 정의',['관리번호']+COLUMN_HEADERS[1:],[[r['code']]+[c[k] for k in COLUMN_FIELDS] for r in rows for c in r['columns']])
    sheet(wb,'점검 및 조치',['관리번호','점검일','점검자','점검 의견','보완 필요','조치 내용','보완 상태','완료일'],[[r['code'],date.fromisoformat(c['date']),c['inspector'],c['opinion'],c['needs_action'],c['action'],c['status'] if c['needs_action'] else '보완 불필요',date.fromisoformat(c['completed_on']) if c['completed_on'] else None] for r in rows for c in r['checks']])
    sheet(wb,'누락 항목',['관리번호','데이터명','누락 항목'],[[r['code'],r['data']['name'],m] for r in rows for m in r['missing']])
    sheet(wb,'추가 항목',['관리번호','항목 키','항목명','필수','활성','입력값'],[[r['code'],f.key,f.label,f.required,f.active,r['data']['extras'].get(f.key,'')] for r in rows for f in definitions])
    result.workbook = workbook_bytes(wb)
    result.save(force_insert=True)
    audit(user,str(result.pk),{}, {'dataset_codes':[r['code'] for r in rows]},operation='제출본 생성')
    return result
