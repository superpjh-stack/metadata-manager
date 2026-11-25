from datetime import timedelta
from io import BytesIO
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from openpyxl import load_workbook
from .models import Dataset, Check, Confirmation
from .services import create_submission

class TaskTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_user('admin',is_staff=True)
        self.owner=get_user_model().objects.create_user('owner')
        self.other=get_user_model().objects.create_user('other')
        self.obj=Dataset.objects.create(name='확인 대상',assignee=self.owner)
        self.check=Check.objects.create(dataset=self.obj,inspector='관리자',opinion='증빙 보완',needs_action=True,action_assignee=self.owner,due_date=timezone.localdate())
        self.client.force_login(self.owner)
    def confirmation_data(self,**kwargs):
        self.obj.refresh_from_db()
        latest=self.obj.latest_confirmation
        return {'revision':self.obj.updated_at.isoformat(),'previous':latest.pk if latest else '', 'outcome':'unchanged','collection_checked':'on','location_checked':'on','conditions_checked':'on',**kwargs}
    def test_tasks_scope_and_render(self):
        other=Dataset.objects.create(name='다른 담당 데이터',assignee=self.other)
        for url in ['/tasks/',reverse('confirm',args=[self.obj.pk]),reverse('action_update',args=[self.obj.pk,self.check.pk]),reverse('detail',args=[self.obj.pk])]:
            self.assertEqual(self.client.get(url).status_code,200)
        response=self.client.get('/tasks/')
        self.assertContains(response,self.obj.name);self.assertNotContains(response,other.name)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/tasks/'),other.name)
        self.assertNotContains(self.client.get('/tasks/?scope=mine'),other.name)
    def test_confirmation_advances_without_metadata_edit_and_duplicate_rejected(self):
        original=self.obj.updated_at
        payload=self.confirmation_data()
        url=reverse('confirm',args=[self.obj.pk])
        self.assertEqual(self.client.post(url,payload).status_code,302)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.updated_at,original)
        self.assertEqual(self.obj.next_confirmation_due,timezone.localdate()+timedelta(days=30))
        self.assertEqual(self.client.post(url,payload).status_code,200)
        self.assertEqual(Confirmation.objects.count(),1)
        self.assertNotContains(self.client.get('/tasks/'),'현황 확인</a>')
    def test_confirmation_requires_checks_and_change_note(self):
        url=reverse('confirm',args=[self.obj.pk])
        self.client.post(url,self.confirmation_data(conditions_checked=''))
        self.client.post(url,self.confirmation_data(outcome='update_required'))
        self.assertFalse(Confirmation.objects.exists())
        self.client.post(url,self.confirmation_data(outcome='update_required',notes='저장 위치 변경 필요'))
        self.obj.refresh_from_db();self.assertTrue(self.obj.confirmation_issue)
        self.assertEqual(self.obj.next_confirmation_due,timezone.localdate())
    def test_reassignment_and_archived_block_processing(self):
        url=reverse('confirm',args=[self.obj.pk]);payload=self.confirmation_data()
        self.obj.assignee=self.other;self.obj.save()
        self.assertEqual(self.client.post(url,payload).status_code,403)
        self.check.action_assignee=self.other;self.check.save()
        self.assertEqual(self.client.get(reverse('action_update',args=[self.obj.pk,self.check.pk])).status_code,403)
        self.obj.archived=True;self.obj.save()
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertNotContains(self.client.get('/tasks/'),self.obj.name)
    def test_edit_invalidates_previous_confirmation(self):
        url=reverse('confirm',args=[self.obj.pk]);payload=self.confirmation_data()
        self.obj.description='변경';self.obj.save()
        self.client.post(url,payload);self.assertFalse(Confirmation.objects.exists())
        self.client.post(url,self.confirmation_data())
        self.obj.refresh_from_db();self.obj.description='재변경';self.obj.save()
        self.assertEqual(self.obj.next_confirmation_due,timezone.localdate())
    def test_manual_and_first_due(self):
        self.obj.confirmation_interval=0;self.obj.save();self.assertIsNone(self.obj.next_confirmation_due)
        self.obj.confirmation_interval=7;self.obj.first_confirmation_due=timezone.localdate()+timedelta(days=10);self.obj.save()
        self.assertEqual(self.obj.next_confirmation_due,self.obj.first_confirmation_due)
    def test_action_submit_stale_and_approval_permissions(self):
        url=reverse('action_update',args=[self.obj.pk,self.check.pk])
        payload={'revision':self.check.updated_at.isoformat(),'action':'증빙 정리','status':'보완 완료'}
        self.client.post(url,payload);self.check.refresh_from_db();self.assertEqual(self.check.status,'보완 필요')
        payload['status']='검토 대기'
        self.assertEqual(self.client.post(url,payload).status_code,302)
        self.check.refresh_from_db();self.assertEqual(self.check.status,'검토 대기');self.assertIsNone(self.check.completed_on)
        payload['action']='오래된 내용';self.client.post(url,payload)
        self.check.refresh_from_db();self.assertEqual(self.check.action,'증빙 정리')
        adminurl=reverse('check_edit',args=[self.obj.pk,self.check.pk])
        self.assertEqual(self.client.post(adminurl,{}).status_code,403)
        self.client.force_login(self.admin)
        response=self.client.post(adminurl,{'revision':self.check.updated_at.isoformat(),'date':str(self.check.date),'inspector':'관리자','opinion':'증빙 보완','needs_action':'on','action_assignee':self.owner.pk,'due_date':str(self.check.due_date),'action':'증빙 정리','status':'보완 완료','completed_on':str(timezone.localdate())})
        self.assertEqual(response.status_code,302)
        self.check.refresh_from_db();self.assertEqual(self.check.approved_by,self.admin)
        self.client.force_login(self.owner);self.assertEqual(self.client.get(url).status_code,403)
    def test_action_due_validation_and_overdue(self):
        self.check.date=timezone.localdate()-timedelta(days=2)
        self.check.due_date=timezone.localdate()-timedelta(days=1);self.check.save()
        self.assertTrue(self.check.is_overdue)
        self.assertContains(self.client.get('/tasks/'),'기한 경과')
        self.check.due_date=self.check.date-timedelta(days=1)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):self.check.full_clean()
    def test_evidence_upload_permission(self):
        from .views import can_upload
        self.assertTrue(can_upload(self.owner,self.obj))
        self.assertFalse(can_upload(self.other,self.obj))
        self.obj.assignee=None;self.obj.save();self.assertTrue(can_upload(self.owner,self.obj))
        self.check.status='보완 완료';self.check.save();self.assertFalse(can_upload(self.owner,self.obj))
    def test_submission_freezes_confirmation_and_action_details(self):
        self.client.post(reverse('confirm',args=[self.obj.pk]),self.confirmation_data())
        result=create_submission(Dataset.objects.filter(pk=self.obj.pk),self.admin)
        data=result.snapshot['datasets'][0]
        self.assertEqual(data['confirmations'][0]['actor'],'owner')
        self.assertEqual(data['checks'][0]['action_assignee'],'owner')
        self.assertEqual(data['data']['confirmation_interval'],30)
        self.assertIn('현황 확인',load_workbook(BytesIO(bytes(result.workbook))).sheetnames)
        frozen=bytes(result.workbook);self.obj.name='변경';self.obj.save();result.refresh_from_db()
        self.assertEqual(bytes(result.workbook),frozen)
