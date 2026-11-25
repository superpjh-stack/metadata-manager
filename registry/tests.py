import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings
from django.urls import reverse
from openpyxl import load_workbook
from .models import Dataset,Column,Check,ExtraField,Submission,Audit,ImportBatch
from .forms import DatasetForm,CheckForm,AttachmentForm,DATA_FIELDS
from .services import import_template,parse_import,save_import,create_submission,values

class WorkflowTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('manager',password='test-only-password',is_staff=True)
        self.viewer=get_user_model().objects.create_user('reader',password='test-only-password')
        self.dataset=Dataset.objects.create(name='온도 이력',created_by=self.user,updated_by=self.user)
        self.client.force_login(self.user)
    def workbook(self,rows=None,cols=None):
        wb=load_workbook(BytesIO(import_template()))
        for data in rows or []:
            wb['데이터셋'].append(data)
        for data in cols or []:
            wb['컬럼 정의'].append(data)
        out=BytesIO(); wb.save(out)
        return SimpleUploadedFile('import.xlsx',out.getvalue())
    def row(self,key='a',**kwargs):
        data={'name':'온도 데이터',**kwargs}
        return [key]+[data.get(k,'') for k in DATA_FIELDS]
    def post_data(self,**kwargs):
        data={k:(getattr(self.dataset,k) or '') for k in DATA_FIELDS}
        data.update({'revision':self.dataset.updated_at.isoformat(),'columns-TOTAL_FORMS':'0','columns-INITIAL_FORMS':'0','columns-MIN_NUM_FORMS':'0','columns-MAX_NUM_FORMS':'1000'})
        data.update(kwargs)
        return data
    def test_all_pages_render(self):
        urls=['/','/datasets/new/',f'/datasets/{self.dataset.pk}/',f'/datasets/{self.dataset.pk}/edit/',f'/datasets/{self.dataset.pk}/checks/new/','/submissions/','/import/','/settings/','/settings/fields/new/','/import/template/']
        for url in urls:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.client.get('/accounts/login/').status_code,200)
    def test_viewer_cannot_mutate_directly(self):
        self.client.force_login(self.viewer)
        for url in ['/datasets/new/',f'/datasets/{self.dataset.pk}/edit/',f'/datasets/{self.dataset.pk}/checks/new/',f'/datasets/{self.dataset.pk}/upload/','/submissions/create/','/import/','/settings/','/settings/fields/new/']:
            with self.subTest(url=url):self.assertEqual(self.client.post(url,{}).status_code,403)
        self.assertEqual(self.client.get('/').status_code,200)
    def test_blank_fields_and_extra_requirement(self):
        self.dataset.owner='   '; self.dataset.save()
        self.assertIn('담당자',self.dataset.missing())
        extra=ExtraField.objects.create(key='asset_id',label='설비 식별자',required=True)
        self.assertIn('설비 식별자',self.dataset.missing())
        self.dataset.extras={'asset_id':'A-01'};self.dataset.save()
        self.assertNotIn('설비 식별자',self.dataset.missing())
        extra.active=False;extra.save();self.dataset.extras={}
        self.assertNotIn('설비 식별자',self.dataset.missing())
    def test_invalid_date_and_status(self):
        for changes in [{'started_on':'2026-02-30'},{'collection_status':'가짜 상태'},{'name':'   '}]:
            form=DatasetForm({'name':'테스트',**changes})
            self.assertFalse(form.is_valid())
    def test_save_persists_and_audits(self):
        response=self.client.post(reverse('edit',args=[self.dataset.pk]),self.post_data(description='수정 내용'))
        self.assertEqual(response.status_code,302)
        self.dataset.refresh_from_db();self.assertEqual(self.dataset.description,'수정 내용')
        audit=Audit.objects.get(dataset=self.dataset)
        self.assertEqual(audit.changes['description'],{'before':'','after':'수정 내용'})
    def test_stale_update_rejected(self):
        payload=self.post_data(description='오래된 편집')
        self.dataset.description='최신';self.dataset.save()
        response=self.client.post(reverse('edit',args=[self.dataset.pk]),payload)
        self.assertContains(response,'다른 작업에서 수정되었습니다.')
        self.dataset.refresh_from_db();self.assertEqual(self.dataset.description,'최신')
    def test_column_create_and_duplicate(self):
        col=Column.objects.create(dataset=self.dataset,name='temp',meaning='온도',dtype='decimal')
        duplicate=Column(dataset=self.dataset,name='temp',meaning='온도2',dtype='decimal')
        with self.assertRaises(ValidationError):duplicate.full_clean()
    def test_check_status_and_validation(self):
        self.assertEqual(self.dataset.review_status,'미점검')
        check=Check.objects.create(dataset=self.dataset,inspector='점검자',opinion='증빙 필요',needs_action=True)
        self.assertEqual(self.dataset.review_status,'보완 필요')
        form=CheckForm({'date':'2026-11-25','inspector':'담당자','opinion':'증빙 필요','needs_action':'on','status':'보완 완료','action':'   ','completed_on':'2026-11-25'},instance=check)
        self.assertFalse(form.is_valid());self.assertIn('action',form.errors)
        check.status='보완 완료';check.action='첨부 완료';check.completed_on=date.today();check.full_clean();check.save()
        self.assertEqual(self.dataset.review_status,'점검 완료')
        Check.objects.create(dataset=self.dataset,inspector='다른 담당자',opinion='추가 보완',needs_action=True)
        self.assertEqual(self.dataset.review_status,'보완 필요')
    def test_import_valid_links_and_missing_warning(self):
        upload=self.workbook([self.row()], [['a','temp','온도','decimal','℃','예','',0]])
        records,errors,warnings=parse_import(upload)
        self.assertFalse(errors);self.assertTrue(warnings)
        result=save_import(records,self.user)
        self.assertEqual(result[0].columns.get().name,'temp')
        self.assertEqual(result[0].columns.get().unit,'℃')
    def test_import_errors(self):
        cases=[([self.row(),self.row()],[], '중복'),([self.row()], [['other','temp','온도','decimal','','','','']], '연결키'),([self.row()], [['a','temp','온도','decimal','','','',''],['a','temp','온도','decimal','','','','']], '중복'),([self.row(started_on='잘못된 날짜')],[], '수집 시작일'),([self.row(collection_status='unknown')],[], '수집 상태')]
        for rows,cols,message in cases:
            with self.subTest(message=message):
                _,errors,_=parse_import(self.workbook(rows,cols));self.assertTrue(any(message in e for e in errors),errors)
    def test_import_atomic_rollback(self):
        records=[{'data':{'name':'첫째'},'columns':[]},{'data':{'name':'둘째'},'columns':[{'name':'temp','meaning':'온도','dtype':'INVALID'}]}]
        before=Dataset.objects.count()
        with self.assertRaises(ValidationError):save_import(records,self.user)
        self.assertEqual(Dataset.objects.count(),before)
    def test_import_preview_single_use(self):
        response=self.client.post('/import/',{'file':self.workbook([self.row()])})
        self.assertContains(response,'가져오기 미리보기')
        batch=ImportBatch.objects.get()
        count=Dataset.objects.count()
        self.assertEqual(self.client.post('/import/',{'confirm':'1','batch':batch.pk}).status_code,302)
        self.assertEqual(Dataset.objects.count(),count+1)
        self.client.post('/import/',{'confirm':'1','batch':batch.pk})
        self.assertEqual(Dataset.objects.count(),count+1)
    def test_failed_import_no_batch(self):
        response=self.client.post('/import/',{'file':self.workbook([self.row(),self.row()])})
        self.assertContains(response,'저장되지 않았습니다.')
        self.assertEqual(ImportBatch.objects.count(),0)
    def test_submission_is_immutable_and_literal(self):
        self.dataset.description='=HYPERLINK("https://example.com")';self.dataset.started_on=date(2026,1,1);self.dataset.save()
        ExtraField.objects.create(key='asset',label='설비 키',required=True)
        submission=create_submission([self.dataset],self.user)
        original=bytes(submission.workbook); snapshot=submission.snapshot
        self.dataset.name='변경된 이름';self.dataset.description='새 내용';self.dataset.save()
        ExtraField.objects.update(label='수정된 항목',active=False)
        submission.refresh_from_db()
        self.assertEqual(bytes(submission.workbook),original);self.assertEqual(submission.snapshot,snapshot)
        wb=load_workbook(BytesIO(original),data_only=False)
        self.assertEqual(wb.sheetnames,['제출정보','데이터 목록','데이터 정의','컬럼 정의','점검 및 조치','누락 항목','추가 항목'])
        self.assertEqual(wb['데이터 정의']['C2'].data_type,'s')
        self.assertTrue(wb['데이터 정의']['C2'].value.startswith('='))
        self.assertEqual(wb['데이터 목록']['B2'].value,'온도 이력')
        self.assertEqual(wb['데이터 정의']['J2'].value.date(),date(2026,1,1))
        for ws in wb:
            self.assertEqual(ws.freeze_panes,'A2');self.assertTrue(ws.auto_filter.ref)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('submission_download',args=[submission.pk])).content,original)
        self.client.logout();self.assertEqual(self.client.get(reverse('submission_download',args=[submission.pk])).status_code,302)
    def test_submission_failure_rolls_back(self):
        with patch('registry.services.workbook_bytes',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):create_submission([self.dataset],self.user)
        self.assertEqual(Submission.objects.count(),0)
    def test_attachment_validation_and_access(self):
        for filename,data in [('evil.html',b'<script>'),('fake.pdf',b'not pdf'),('big.csv',b'a'*(10*1024*1024+1))]:
            form=AttachmentForm({}, {'file':SimpleUploadedFile(filename,data)})
            self.assertFalse(form.is_valid())
        with tempfile.TemporaryDirectory() as tmp,override_settings(MEDIA_ROOT=tmp):
            response=self.client.post(reverse('upload',args=[self.dataset.pk]),{'file':SimpleUploadedFile('proof.csv','값\n1'.encode()),'description':'증빙'})
            self.assertEqual(response.status_code,302)
            attachment=self.dataset.attachments.get()
            self.client.force_login(self.viewer)
            response=self.client.get(reverse('attachment',args=[attachment.pk]));self.assertEqual(response.status_code,200)
            self.assertEqual(b''.join(response.streaming_content),'값\n1'.encode())
            self.client.logout();self.assertEqual(self.client.get(reverse('attachment',args=[attachment.pk])).status_code,302)
    def test_search_filters(self):
        self.dataset.process='가공';self.dataset.save()
        self.assertContains(self.client.get('/',{'q':self.dataset.code}),'온도 이력')
        self.assertNotContains(self.client.get('/',{'process':'없는 공정'}),'온도 이력')
    def test_submission_requires_selection(self):
        response=self.client.post('/submissions/create/',{},follow=True)
        self.assertContains(response,'제출 대상을 선택하세요.')
        self.assertEqual(Submission.objects.count(),0)
    def test_extra_key_is_immutable(self):
        field=ExtraField.objects.create(key='original',label='원본')
        self.client.post(reverse('extra_edit',args=[field.pk]),{'key':'changed','label':'수정','active':'on','order':'0'})
        field.refresh_from_db();self.assertEqual(field.key,'original')
    def test_create_edit_column_and_complete_review_flow(self):
        payload=self.post_data(name='새 품질 데이터')
        payload.update({'columns-TOTAL_FORMS':'1','columns-0-name':'result','columns-0-meaning':'검사 결과','columns-0-dtype':'text','columns-0-order':'0'})
        response=self.client.post('/datasets/new/',payload)
        self.assertEqual(response.status_code,302)
        obj=Dataset.objects.get(name='새 품질 데이터')
        self.assertEqual(obj.columns.get().name,'result')
        response=self.client.post(reverse('check_create',args=[obj.pk]),{'date':'2026-11-25','inspector':'담당자','opinion':'보완 내용','needs_action':'on','status':'보완 필요'})
        self.assertEqual(response.status_code,302)
        check=obj.checks.get();self.assertEqual(obj.review_status,'보완 필요')
        response=self.client.post(reverse('check_edit',args=[obj.pk,check.pk]),{'date':'2026-11-25','inspector':'담당자','opinion':'보완 내용','needs_action':'on','status':'보완 완료','action':'보완 조치 완료','completed_on':'2026-11-25'})
        self.assertEqual(response.status_code,302);self.assertEqual(obj.review_status,'점검 완료')
        self.assertEqual(Audit.objects.filter(dataset=obj).count(),3)
    def test_nonexistent_submission_target_rejected(self):
        response=self.client.post('/submissions/create/',{'datasets':'999999'},follow=True)
        self.assertContains(response,'존재하지 않습니다.')
        self.assertEqual(Submission.objects.count(),0)
    def test_import_formula_rejected(self):
        _,errors,_=parse_import(self.workbook([self.row(name='=1+1')]))
        self.assertTrue(any('수식' in e for e in errors))
    def test_extra_value_survives_deactivation_and_edit(self):
        extra=ExtraField.objects.create(key='aas_id',label='AAS 식별자',required=True)
        response=self.client.post(reverse('edit',args=[self.dataset.pk]),self.post_data(extra_aas_id='asset-01'))
        self.assertEqual(response.status_code,302)
        self.dataset.refresh_from_db();self.assertEqual(self.dataset.extras['aas_id'],'asset-01')
        extra.active=False;extra.save()
        response=self.client.post(reverse('edit',args=[self.dataset.pk]),self.post_data(description='변경'))
        self.dataset.refresh_from_db();self.assertEqual(self.dataset.extras['aas_id'],'asset-01')
    def test_column_removal_is_audited(self):
        column=Column.objects.create(dataset=self.dataset,name='old',meaning='이전 컬럼',dtype='text')
        payload=self.post_data()
        payload.update({'columns-TOTAL_FORMS':'1','columns-INITIAL_FORMS':'1','columns-0-id':str(column.pk),'columns-0-dataset':str(self.dataset.pk),'columns-0-name':'old','columns-0-meaning':'이전 컬럼','columns-0-dtype':'text','columns-0-order':'0','columns-0-DELETE':'on'})
        response=self.client.post(reverse('edit',args=[self.dataset.pk]),payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.dataset.columns.count(),0)
        changes=Audit.objects.get(dataset=self.dataset).changes['columns']
        self.assertEqual(changes['before'][0]['name'],'old');self.assertEqual(changes['after'],[])
