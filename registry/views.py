from datetime import timedelta
from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Dataset, Check, Column, Project, ExtraField, Attachment, Submission, ImportBatch, Confirmation
from .forms import DatasetForm, ColumnFormSet, CheckForm, ProjectForm, ExtraForm, AttachmentForm, AssigneeAccountForm, ConfirmationForm, ActionForm, DATA_FIELDS
from .services import values, audit, import_template, parse_import, save_import, create_submission

def health(request):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return HttpResponse('ok',content_type='text/plain')

def manager_only(view):
    @login_required
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request,*args,**kwargs)
    return wrapped

def queryset():
    return Dataset.objects.filter(archived=False).select_related('assignee').prefetch_related('checks__action_assignee','columns','confirmations__actor')

@login_required
def overview(request):
    return render(request,'registry/overview.html')

@login_required
def index(request):
    all_rows = list(queryset())
    definitions = list(ExtraField.objects.filter(active=True))
    summary = {'total':len(all_rows),'missing':sum(bool(d.missing(definitions)) for d in all_rows),'action':sum(d.review_status=='보완 필요' for d in all_rows)}
    rows = all_rows
    assignment = request.GET.get('assignment','')
    if assignment == 'mine':
        rows = [d for d in rows if d.assignee_id == request.user.pk]
    elif assignment == 'unassigned':
        rows = [d for d in rows if d.assignee_id is None]
    elif assignment == 'inactive':
        rows = [d for d in rows if d.assignee_id and not d.assignee.is_active]
    elif assignment:
        rows = [d for d in rows if str(d.assignee_id) == assignment]
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
    return render(request,'registry/index.html',{'rows':rows,'summary':summary,'assignment':assignment,'assignees':get_user_model().objects.filter(assigned_datasets__archived=False).distinct().order_by('username'),'processes':sorted({d.process for d in all_rows if d.process}),'equipments':sorted({d.equipment for d in all_rows if d.equipment}),'collections':['준비 중','수집 중','일시 중단','종료'],'inputs':['미입력 있음','입력 완료'],'reviews':['미점검','보완 필요','점검 완료']})

@login_required
def detail(request,pk):
    obj = get_object_or_404(queryset(),pk=pk)
    labels = [(str(obj._meta.get_field(k).verbose_name),getattr(obj,k)) for k in DATA_FIELDS if k!='name']
    extras = [(f.label,obj.extras.get(f.key,''),f.active) for f in ExtraField.objects.all()]
    return render(request,'registry/detail.html',{'obj':obj,'labels':labels,'extras':extras,'missing':obj.missing(),'can_confirm':request.user.is_staff or obj.assignee_id==request.user.pk,'can_upload':can_upload(request.user,obj),'attachment_form':AttachmentForm(),'audits':obj.audits.select_related('actor')[:30]})

@manager_only
def edit(request,pk=None):
    obj = get_object_or_404(Dataset,pk=pk,archived=False) if pk else Dataset()
    before = values(obj) if pk else {}
    before['assignee_details'] = obj.assignee_snapshot()
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
                    after['assignee_details']=obj.assignee_snapshot()
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
            current=Check.objects.select_for_update().get(pk=check_id) if check_id else None
            if current and form.cleaned_data['revision'] != current.updated_at.isoformat():
                form.add_error(None,'다른 작업에서 변경되었습니다. 페이지를 다시 열어 확인하세요.')
                return render(request,'registry/form.html',{'form':form,'title':'점검 및 조치 기록','back':f'/datasets/{pk}/'},status=409)
            check=form.save(commit=False)
            if check.needs_action and check.status=='보완 완료':
                check.approved_by=request.user
                check.approved_at=timezone.now()
            else:
                check.approved_by=None
                check.approved_at=None
            check.save()
            audit(request.user,f'{obj.code} 점검 #{check.pk}',before,values(check),obj,'점검 수정' if check_id else '점검 등록')
        messages.success(request,'점검 기록을 저장했습니다.')
        return redirect('detail',pk=pk)
    return render(request,'registry/form.html',{'form':form,'title':'점검 및 조치 기록','subtitle':obj.name,'back':f'/datasets/{pk}/'})

@login_required
@require_POST
def upload(request,pk):
    obj=get_object_or_404(Dataset,pk=pk,archived=False)
    if not can_upload(request.user,obj):raise PermissionDenied
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

@manager_only
def accounts(request):
    users = get_user_model().objects.annotate(
        dataset_count=Count('assigned_datasets',filter=Q(assigned_datasets__archived=False))
    ).order_by('-is_active','username')
    return render(request,'registry/accounts.html',{'accounts':users})

@manager_only
def account_create(request):
    form = AssigneeAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            audit(request.user,f'담당 계정 {user.username}',{},
                  {'username':user.username,'name':user.get_full_name(),'role':'담당자'},operation='계정 등록')
        messages.success(request,f'{user.username} 계정을 등록했습니다. 데이터 수정 화면에서 담당 계정으로 연결하세요.')
        return redirect('accounts')
    return render(request,'registry/form.html',{'form':form,'title':'담당자 계정 등록',
        'subtitle':'배정된 현황 확인·조치를 처리할 일반 계정을 생성합니다. 비밀번호는 담당자에게 별도로 전달하세요.',
        'back':'/settings/accounts/'})


def can_upload(user,obj):
    return user.is_staff or obj.assignee_id==user.pk or obj.checks.filter(action_assignee=user,needs_action=True).exclude(status='보완 완료').exists()

@login_required
def tasks(request):
    today=timezone.localdate()
    all_scope=request.user.is_staff and request.GET.get('scope')!='mine'
    datasets=list(queryset())
    owned=datasets if all_scope else [d for d in datasets if d.assignee_id==request.user.pk]
    confirmations=[d for d in owned if d.next_confirmation_due and d.next_confirmation_due<=today+timedelta(days=7)]
    confirmations.sort(key=lambda d:(d.next_confirmation_due,d.pk))
    actions=Check.objects.filter(dataset__archived=False,needs_action=True).exclude(status='보완 완료').select_related('dataset','action_assignee')
    if not all_scope:actions=actions.filter(action_assignee=request.user)
    actions=sorted(actions,key=lambda c:(0 if c.is_overdue else 1 if c.status=='검토 대기' else 2,c.due_date or today+timedelta(days=36500),c.pk))
    return render(request,'registry/tasks.html',{'confirmations':confirmations,'actions':actions,'all_scope':all_scope,'today':today,'owned_count':len(owned),'overdue_count':sum(d.next_confirmation_due<today for d in confirmations)+sum(c.is_overdue for c in actions),'review_count':sum(c.status=='검토 대기' for c in actions),'unassigned':[d for d in datasets if not d.assignee_id or not d.assignee.is_active] if all_scope else []})

@login_required
def confirm(request,pk):
    with transaction.atomic():
        obj=get_object_or_404(Dataset.objects.select_for_update(),pk=pk,archived=False)
        if not (request.user.is_staff or obj.assignee_id==request.user.pk):raise PermissionDenied
        latest=obj.latest_confirmation
        form=ConfirmationForm(request.POST or None,initial={'revision':obj.updated_at.isoformat(),'previous':latest.pk if latest else None})
        if request.method=='POST' and form.is_valid():
            if form.cleaned_data['revision']!=obj.updated_at.isoformat() or form.cleaned_data['previous']!=(latest.pk if latest else None):
                form.add_error(None,'내용이나 확인 이력이 변경되었습니다. 페이지를 다시 열어 확인하세요.')
            else:
                item=Confirmation.objects.create(dataset=obj,actor=request.user,outcome=form.cleaned_data['outcome'],notes=form.cleaned_data['notes'],snapshot={'data':values(obj),'assignee':obj.assignee_snapshot(),'actor':request.user.username,'checks':{k:form.cleaned_data[k] for k in ['collection_checked','location_checked','conditions_checked']}})
                audit(request.user,f'{obj.code} 현황 확인',{},values(item),obj,'현황 확인')
                messages.success(request,'현황 확인을 기록했습니다.' if item.outcome=='unchanged' else '변경 필요 사항을 기록했습니다. 관리자에게 데이터 수정을 요청하세요.')
                return redirect('tasks')
    return render(request,'registry/confirm.html',{'form':form,'obj':obj})

@login_required
def action_update(request,pk,check_id):
    with transaction.atomic():
        check=get_object_or_404(Check.objects.select_for_update().select_related('dataset'),pk=check_id,dataset_id=pk,dataset__archived=False,needs_action=True)
        if not (request.user.is_staff or check.action_assignee_id==request.user.pk):raise PermissionDenied
        if check.status=='보완 완료':raise PermissionDenied
        form=ActionForm(request.POST or None,initial={'revision':check.updated_at.isoformat(),'action':check.action,'status':check.status if check.status in ['보완 중','검토 대기'] else '보완 중'})
        if request.method=='POST' and form.is_valid():
            if form.cleaned_data['revision']!=check.updated_at.isoformat():
                form.add_error(None,'조치가 변경되었습니다. 페이지를 다시 열어 확인하세요.')
            else:
                before=values(check)
                check.action=form.cleaned_data['action'];check.status=form.cleaned_data['status']
                check.completed_on=None;check.approved_by=None;check.approved_at=None
                check.save()
                audit(request.user,f'{check.dataset.code} 조치 #{check.pk}',before,values(check),check.dataset,'조치 제출')
                messages.success(request,'조치 내용을 저장했습니다. 검토 요청 후에는 관리자가 최종 완료를 확인합니다.')
                return redirect('tasks')
    return render(request,'registry/form.html',{'form':form,'title':'보완 조치 처리','subtitle':f'{check.dataset.name} · {check.opinion} · 기한 {check.due_date or "미지정"}','back':f'/datasets/{pk}/'})
