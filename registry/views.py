from datetime import timedelta
from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Dataset, Check, Column, Project, ExtraField, Attachment, Submission, ImportBatch
from .forms import DatasetForm, ColumnFormSet, CheckForm, ProjectForm, ExtraForm, AttachmentForm, DATA_FIELDS
from .services import values, audit, import_template, parse_import, save_import, create_submission

def manager_only(view):
    @login_required
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request,*args,**kwargs)
    return wrapped

def queryset():
    return Dataset.objects.filter(archived=False).prefetch_related('checks','columns')

@login_required
def overview(request):
    return render(request,'registry/overview.html')

@login_required
def index(request):
    all_rows = list(queryset())
    definitions = list(ExtraField.objects.filter(active=True))
    summary = {'total':len(all_rows),'missing':sum(bool(d.missing(definitions)) for d in all_rows),'action':sum(d.review_status=='보완 필요' for d in all_rows)}
    rows = all_rows
    query = request.GET.get('q','').strip().lower()
    if query:
        rows = [d for d in rows if query in d.name.lower() or query in d.code.lower()]
    for field in ['process','equipment','collection_status']:
        selected = request.GET.get(field,'')
        if selected:
            rows = [d for d in rows if getattr(d,field)==selected]
    if request.GET.get('input_status'):
        rows = [d for d in rows if ('미입력 있음' if d.missing(definitions) else '입력 완료')==request.GET['input_status']]
    if request.GET.get('review_status'):
        rows = [d for d in rows if d.review_status==request.GET['review_status']]
    for d in rows:
        d.missing_items = d.missing(definitions)
    return render(request,'registry/index.html',{'rows':rows,'summary':summary,'processes':sorted({d.process for d in all_rows if d.process}),'equipments':sorted({d.equipment for d in all_rows if d.equipment}),'collections':['준비 중','수집 중','일시 중단','종료'],'inputs':['미입력 있음','입력 완료'],'reviews':['미점검','보완 필요','점검 완료']})

@login_required
def detail(request,pk):
    obj = get_object_or_404(queryset(),pk=pk)
    labels = [(str(obj._meta.get_field(k).verbose_name),getattr(obj,k)) for k in DATA_FIELDS if k!='name']
    extras = [(f.label,obj.extras.get(f.key,''),f.active) for f in ExtraField.objects.all()]
    return render(request,'registry/detail.html',{'obj':obj,'labels':labels,'extras':extras,'missing':obj.missing(),'attachment_form':AttachmentForm(),'audits':obj.audits.select_related('actor')[:30]})

@manager_only
def edit(request,pk=None):
    obj = get_object_or_404(Dataset,pk=pk,archived=False) if pk else Dataset()
    before = values(obj) if pk else {}
    before_cols = [values(c) for c in obj.columns.all()] if pk else []
    form = DatasetForm(request.POST or None,instance=obj)
    formset = ColumnFormSet(request.POST or None,instance=obj,prefix='columns')
    if request.method=='POST':
        valid = form.is_valid()
        cols_valid = formset.is_valid()
        if valid and cols_valid:
            with transaction.atomic():
                if pk and Dataset.objects.get(pk=pk).updated_at.isoformat()!=form.cleaned_data['revision']:
                    form.add_error(None,'다른 작업에서 수정되었습니다. 현재 내용을 복사해 둔 뒤 페이지를 새로 열어 최신 내용을 확인하세요.')
                else:
                    obj = form.save(commit=False)
                    if not pk:
                        obj.created_by=request.user
                    obj.updated_by=request.user
                    obj.save()
                    formset.instance=obj
                    formset.save()
                    after=values(obj)
                    before['columns']=before_cols
                    after['columns']=[values(c) for c in obj.columns.all()]
                    audit(request.user,obj.code,before,after,obj,'수정' if pk else '등록')
                    messages.success(request,'저장했습니다. 미입력 항목은 상세 화면에서 확인하세요.')
                    return redirect('detail',pk=obj.pk)
    return render(request,'registry/edit.html',{'obj':obj,'form':form,'formset':formset})

@manager_only
def check_edit(request,pk,check_id=None):
    obj=get_object_or_404(Dataset,pk=pk,archived=False)
    check=get_object_or_404(Check,pk=check_id,dataset=obj) if check_id else Check(dataset=obj)
    before=values(check) if check_id else {}
    form=CheckForm(request.POST or None,instance=check)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            check=form.save()
            audit(request.user,f'{obj.code} 점검 #{check.pk}',before,values(check),obj,'점검 수정' if check_id else '점검 등록')
        messages.success(request,'점검 기록을 저장했습니다.')
        return redirect('detail',pk=pk)
    return render(request,'registry/form.html',{'form':form,'title':'점검 및 조치 기록','subtitle':obj.name,'back':f'/datasets/{pk}/'})

@manager_only
@require_POST
def upload(request,pk):
    obj=get_object_or_404(Dataset,pk=pk,archived=False)
    form=AttachmentForm(request.POST,request.FILES)
    if form.is_valid():
        attachment=Attachment(dataset=obj,file=form.cleaned_data['file'],original_name=Path(form.cleaned_data['file'].name).name,description=form.cleaned_data['description'],uploaded_by=request.user)
        try:
            with transaction.atomic():
                attachment.save()
                audit(request.user,f'{obj.code} 첨부',{}, {'name':attachment.original_name,'description':attachment.description},obj,'첨부')
        except Exception:
            if attachment.file.name:
                attachment.file.delete(save=False)
            raise
        messages.success(request,'증빙 파일을 첨부했습니다.')
        return redirect('detail',pk=pk)
    return render(request,'registry/form.html',{'form':form,'title':'증빙 첨부','subtitle':obj.name,'multipart':True,'back':f'/datasets/{pk}/'},status=400)

@login_required
def attachment_download(request,pk):
    item=get_object_or_404(Attachment,pk=pk)
    try:
        return FileResponse(item.file.open('rb'),as_attachment=True,filename=item.original_name)
    except FileNotFoundError:
        raise Http404('파일이 없습니다. 백업 복구 상태를 확인하세요.')

@login_required
def submissions(request):
    rows=list(queryset())
    definitions=list(ExtraField.objects.filter(active=True))
    for row in rows:
        row.missing_items=row.missing(definitions)
        row.pending_checks=[c for c in row.checks.all() if c.needs_action and c.status!='보완 완료']
    return render(request,'registry/submissions.html',{'rows':rows,'submissions':Submission.objects.select_related('created_by'),'project':Project.objects.first()})

@manager_only
@require_POST
def submit_create(request):
    ids=request.POST.getlist('datasets')
    if not ids or any(not x.isdigit() for x in ids):
        messages.error(request,'제출 대상을 선택하세요.'); return redirect('submissions')
    selected = queryset().filter(pk__in=ids)
    if selected.count() != len(set(ids)):
        messages.error(request,'선택한 데이터가 변경되었거나 존재하지 않습니다. 목록을 다시 확인하세요.')
        return redirect('submissions')
    create_submission(selected,request.user)
    messages.success(request,'제출본을 생성했습니다. 이후 원본이 바뀌어도 이 제출본은 유지됩니다.')
    return redirect('submissions')

@login_required
def submission_download(request,pk):
    obj=get_object_or_404(Submission,pk=pk)
    return xlsx_response(bytes(obj.workbook),f'metadata_{timezone.localtime(obj.created_at):%Y%m%d}_{obj.pk}.xlsx')

def xlsx_response(data,name):
    response=HttpResponse(data,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition']=f'attachment; filename="{name}"'
    return response

@manager_only
def template_download(request):
    return xlsx_response(import_template(),'metadata_import_template.xlsx')

@manager_only
def import_data(request):
    context={}
    if request.method=='POST':
        if request.POST.get('confirm'):
            with transaction.atomic():
                try:
                    batch=ImportBatch.objects.get(pk=request.POST.get('batch'),user=request.user,consumed=False,created_at__gte=timezone.now()-timedelta(hours=1))
                except (ImportBatch.DoesNotExist,ValidationError):
                    messages.error(request,'미리보기가 만료되었거나 이미 저장되었습니다. 다시 업로드하세요.')
                    return redirect('import')
                claimed=ImportBatch.objects.filter(pk=batch.pk,consumed=False).update(consumed=True)
                if not claimed:
                    messages.error(request,'이미 저장된 가져오기입니다.'); return redirect('import')
                created=save_import(batch.payload,request.user)
                ImportBatch.objects.filter(pk=batch.pk).update(payload=[])
            messages.success(request,f'{len(created)}개 데이터셋을 신규 등록했습니다.')
            return redirect('index')
        upload=request.FILES.get('file')
        if not upload:
            context['errors']=['파일을 선택하세요.']
        else:
            records,errors,warnings=parse_import(upload)
            context.update(records=records,errors=errors,warnings=warnings)
            if not errors:
                ImportBatch.objects.filter(user=request.user,created_at__lt=timezone.now()-timedelta(hours=1)).delete()
                batch=ImportBatch.objects.create(user=request.user,payload=records)
                context['batch']=batch
    return render(request,'registry/import.html',context)

@manager_only
def settings_view(request):
    obj,_=Project.objects.get_or_create(pk=1)
    before=values(obj)
    form=ProjectForm(request.POST or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            form.save(); audit(request.user,'사업 설정',before,values(obj))
        messages.success(request,'사업 설정을 저장했습니다.'); return redirect('settings')
    return render(request,'registry/settings.html',{'form':form,'definitions':ExtraField.objects.all()})

@manager_only
def extra_edit(request,pk=None):
    obj=get_object_or_404(ExtraField,pk=pk) if pk else ExtraField()
    before=values(obj) if pk else {}
    form=ExtraForm(request.POST or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            form.save(); audit(request.user,f'추가 항목 {obj.key}',before,values(obj),operation='항목 설정')
        messages.success(request,'추가 항목을 저장했습니다.'); return redirect('settings')
    return render(request,'registry/form.html',{'form':form,'title':'추가 항목 설정','subtitle':'기존 값과 제출본은 유지됩니다. 항목 제거는 비활성화를 사용하세요.','back':'/settings/'})
