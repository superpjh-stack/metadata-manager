from pathlib import Path
from zipfile import ZipFile, BadZipFile
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.forms import inlineformset_factory
from .models import Dataset, Column, Check, Project, ExtraField, REQUIRED

DATA_FIELDS = ['name','description','process','equipment','owner','source','method','frequency','started_on','location','format','retention','collection_status','rights_owner','manager','purpose','access','sharing','conditions']
class DatasetForm(forms.ModelForm):
    revision = forms.CharField(widget=forms.HiddenInput,required=False)
    class Meta:
        model = Dataset
        fields = DATA_FIELDS[:5] + ['assignee','confirmation_interval','first_confirmation_due'] + DATA_FIELDS[5:]
        widgets = {'started_on':forms.DateInput(attrs={'type':'date'}),'first_confirmation_due':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['confirmation_interval'].required = False
        self.fields['confirmation_interval'].help_text = '최초 확인 후 확인일을 기준으로 다음 기한을 계산합니다. 수시는 자동 기한을 만들지 않습니다.'
        self.fields['first_confirmation_due'].help_text = '미입력 시 등록일. 이미 확인한 데이터는 마지막 확인일과 주기로 계산합니다.'
        self.original_assignee_id = self.instance.assignee_id
        self.fields['assignee'].queryset = get_user_model().objects.filter(
            Q(is_active=True) | Q(pk=self.original_assignee_id)).order_by('first_name','username')
        self.fields['assignee'].label_from_instance = lambda user: (
            f'{user.get_full_name().strip()} ({user.username})' if user.get_full_name().strip() else user.username
        ) + (' · 비활성' if not user.is_active else '')
        self.fields['assignee'].empty_label = '계정 미연결'
        self.fields['assignee'].help_text = '실제 로그인 계정을 선택하세요. 담당자는 배정 데이터의 현황 확인과 증빙 첨부를 할 수 있습니다. 정의 수정은 관리자 전용입니다.'
        self.fields['owner'].label = '담당자 표기명'
        self.fields['owner'].help_text = '기존 이름·외부 담당자명은 그대로 보존합니다. 비어 있으면 선택한 계정 이름으로 채웁니다.'
        if self.instance.pk:
            self.fields['revision'].initial = self.instance.updated_at.isoformat()
        for field in self.fields.values():
            if isinstance(field.widget,forms.Textarea):
                field.widget.attrs['rows'] = 3
        for name in REQUIRED:
            self.fields[name].metadata_required = True
        self.definitions = list(ExtraField.objects.filter(active=True))
        for definition in self.definitions:
            self.fields['extra_'+definition.key] = forms.CharField(label=definition.label,help_text=definition.description,required=False,widget=forms.Textarea(attrs={'rows':3}) if definition.multiline else forms.TextInput,initial=self.instance.extras.get(definition.key,''))
            self.fields['extra_'+definition.key].metadata_required = definition.required
    def clean(self):
        data = super().clean()
        if data.get('confirmation_interval') is None:
            data['confirmation_interval'] = self.instance.confirmation_interval
        assignee = data.get('assignee')
        if assignee and not assignee.is_active and assignee.pk != self.original_assignee_id:
            self.add_error('assignee','비활성 계정은 새 담당자로 지정할 수 없습니다.')
        if assignee and not data.get('owner'):
            data['owner'] = (assignee.get_full_name().strip() or assignee.username)[:100]
        return data
    def save(self,commit=True):
        obj = super().save(commit=False)
        obj.extras = dict(obj.extras)
        for definition in self.definitions:
            obj.extras[definition.key] = self.cleaned_data['extra_'+definition.key]
        if commit:
            obj.save()
        return obj

ColumnFormSet = inlineformset_factory(Dataset,Column,fields=['name','meaning','dtype','unit','required','notes','order'],extra=1,can_delete=True)

class AssigneeAccountForm(UserCreationForm):
    first_name = forms.CharField(label='이름',max_length=100)
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username','first_name']
    def save(self,commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        user.is_superuser = False
        user.is_active = True
        if commit:
            user.save()
        return user

class CheckForm(forms.ModelForm):
    revision = forms.CharField(widget=forms.HiddenInput,required=False)
    class Meta:
        model = Check
        fields = ['date','inspector','opinion','needs_action','action_assignee','due_date','status','action','completed_on']
        widgets = {'due_date':forms.DateInput(attrs={'type':'date'}),'date':forms.DateInput(attrs={'type':'date'}),'completed_on':forms.DateInput(attrs={'type':'date'}),'opinion':forms.Textarea(attrs={'rows':3}),'action':forms.Textarea(attrs={'rows':3})}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['action_assignee'].queryset = get_user_model().objects.filter(Q(is_active=True)|Q(pk=self.instance.action_assignee_id)).order_by('username')
        self.fields['action_assignee'].label_from_instance = lambda u: (u.get_full_name().strip() or u.username) + f' ({u.username})' + (' · 비활성' if not u.is_active else '')
        self.fields['action_assignee'].empty_label = '담당자 미지정'
        if self.instance.pk:
            self.fields['revision'].initial = self.instance.updated_at.isoformat()

class ConfirmationForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)
    previous = forms.IntegerField(widget=forms.HiddenInput,required=False)
    outcome = forms.ChoiceField(label='확인 결과',choices=[('unchanged','변경 없음'),('update_required','변경 필요')])
    collection_checked = forms.BooleanField(label='현재 수집 상태를 직접 확인했습니다.',required=False)
    location_checked = forms.BooleanField(label='저장 위치와 담당자를 직접 확인했습니다.',required=False)
    conditions_checked = forms.BooleanField(label='권리·이용조건의 변경 여부를 직접 확인했습니다.',required=False)
    notes = forms.CharField(label='변경사항 또는 참고 메모',required=False,widget=forms.Textarea(attrs={'rows':4}))
    def clean(self):
        data=super().clean()
        if data.get('outcome') == 'unchanged':
            for key in ['collection_checked','location_checked','conditions_checked']:
                if not data.get(key):self.add_error(key,'변경 없음 기록 전에 이 항목을 확인하세요.')
        elif data.get('outcome') == 'update_required' and not data.get('notes'):
            self.add_error('notes','변경이 필요한 내용을 입력하세요.')
        return data

class ActionForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)
    action = forms.CharField(label='조치 내용',widget=forms.Textarea(attrs={'rows':5}))
    status = forms.ChoiceField(label='처리 상태',choices=[('보완 중','조치 중으로 저장'),('검토 대기','조치 완료 · 관리자 검토 요청')])

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['company','name','start','end']
        widgets = {'start':forms.DateInput(attrs={'type':'date'}),'end':forms.DateInput(attrs={'type':'date'})}

class ExtraForm(forms.ModelForm):
    class Meta:
        model = ExtraField
        fields = ['key','label','description','multiline','required','active','order']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk:
            self.fields['key'].disabled = True

class AttachmentForm(forms.Form):
    file = forms.FileField(label='증빙 파일',help_text='PDF, PNG, JPG, XLSX, CSV · 최대 10MB')
    description = forms.CharField(label='설명',max_length=250,required=False)
    def clean_file(self):
        f = self.cleaned_data['file']
        if f.size > 10*1024*1024:
            raise forms.ValidationError('파일은 최대 10MB입니다.')
        suffix = Path(f.name).suffix.lower()
        head = f.read(16)
        f.seek(0)
        signatures = {'.pdf':b'%PDF-', '.png':b'\x89PNG\r\n\x1a\n', '.jpg':b'\xff\xd8\xff', '.jpeg':b'\xff\xd8\xff'}
        if suffix in signatures:
            if not head.startswith(signatures[suffix]):
                raise forms.ValidationError('파일 내용과 확장자가 일치하지 않습니다.')
        elif suffix == '.xlsx':
            try:
                with ZipFile(f) as z:
                    if 'xl/workbook.xml' not in z.namelist():
                        raise ValueError()
            except (BadZipFile,ValueError):
                raise forms.ValidationError('올바른 XLSX 파일이 아닙니다.')
        elif suffix == '.csv':
            try:
                f.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                raise forms.ValidationError('CSV는 UTF-8 형식으로 저장하세요.')
        else:
            raise forms.ValidationError('허용되지 않은 파일 형식입니다.')
        f.seek(0)
        return f
