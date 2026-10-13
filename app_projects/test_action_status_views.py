from django.urls import reverse

from app_projects.models import Action, ActionEvent
from app_projects.test_action_views import ActionViewBase


class StatusRouteBase(ActionViewBase):
    def status_url(self, action, project=None):
        return reverse("projectActionStatus", args=[(project or self.pa).uuid, action.uuid])

    def reassign_url(self, action, project=None):
        return reverse("projectActionReassign", args=[(project or self.pa).uuid, action.uuid])

    def delete_url(self, action, project=None):
        return reverse("projectActionDelete", args=[(project or self.pa).uuid, action.uuid])


class StatusViewTests(StatusRouteBase):
    def test_assignee_changes_status_and_event_is_written(self):
        self.login(self.worker)
        r = self.client.post(self.status_url(self.a1), {"status": "in_progress"})
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "in_progress")
        self.assertEqual(self.a1.events.filter(kind=ActionEvent.KIND_STATUS).count(), 1)

    def test_admin_changes_status_of_any_action(self):
        self.login(self.admin)
        self.client.post(self.status_url(self.a2), {"status": "review"})
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, "review")

    def test_done_sets_completed_at(self):
        self.login(self.worker)
        self.client.post(self.status_url(self.a1), {"status": "done"})
        self.a1.refresh_from_db()
        self.assertIsNotNone(self.a1.completed_at)

    def test_non_assignee_member_gets_403(self):
        self.login(self.mate)
        r = self.client.post(self.status_url(self.a1), {"status": "done"})
        self.assertEqual(r.status_code, 403)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "todo")

    def test_invalid_status_is_rejected(self):
        self.login(self.admin)
        r = self.client.post(self.status_url(self.a1), {"status": "bogus"})
        self.assertEqual(r.status_code, 302)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "todo")
        self.assertEqual(self.a1.events.filter(kind=ActionEvent.KIND_STATUS).count(), 0)

    def test_missing_status_is_rejected(self):
        self.login(self.admin)
        self.client.post(self.status_url(self.a1), {})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "todo")

    def test_get_is_405(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.status_url(self.a1)).status_code, 405)

    def test_anonymous_is_sent_to_login(self):
        r = self.client.post(self.status_url(self.a1), {"status": "done"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_other_project_member_gets_404(self):
        self.login(self.beta_user)
        r = self.client.post(self.status_url(self.a1), {"status": "done"})
        self.assertEqual(r.status_code, 404)

    def test_other_org_gets_404(self):
        self.login(self.outsider)
        r = self.client.post(self.status_url(self.a1), {"status": "done"})
        self.assertEqual(r.status_code, 404)

    def test_wrong_project_in_url_gets_404(self):
        self.login(self.admin)
        r = self.client.post(self.status_url(self.a1, project=self.pb), {"status": "done"})
        self.assertEqual(r.status_code, 404)

    def test_archived_project_blocks_change(self):
        self.pa.archive()
        self.login(self.admin)
        self.client.post(self.status_url(self.a1), {"status": "done"})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "todo")


class ReassignViewTests(StatusRouteBase):
    def test_admin_reassigns_and_event_is_written(self):
        self.login(self.admin)
        r = self.client.post(self.reassign_url(self.a1), {"assignee": self.mate_p.pk})
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.assignee_id, self.mate_p.pk)
        self.assertEqual(self.a1.events.filter(kind=ActionEvent.KIND_ASSIGNEE).count(), 1)

    def test_admin_can_unassign(self):
        self.login(self.admin)
        self.client.post(self.reassign_url(self.a1), {"assignee": ""})
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.assignee_id)

    def test_assignee_cannot_reassign(self):
        self.login(self.worker)
        r = self.client.post(self.reassign_url(self.a1), {"assignee": self.mate_p.pk})
        self.assertEqual(r.status_code, 403)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.assignee_id, self.worker_p.pk)

    def test_plain_member_gets_403(self):
        self.login(self.mate)
        r = self.client.post(self.reassign_url(self.a1), {"assignee": self.mate_p.pk})
        self.assertEqual(r.status_code, 403)

    def test_assignee_from_other_project_is_rejected(self):
        self.login(self.admin)
        self.client.post(self.reassign_url(self.a1), {"assignee": self.beta_p.pk})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.assignee_id, self.worker_p.pk)

    def test_assignee_from_other_org_is_rejected(self):
        self.login(self.admin)
        self.client.post(self.reassign_url(self.a1), {"assignee": self.outsider_p.pk})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.assignee_id, self.worker_p.pk)

    def test_get_is_405(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.reassign_url(self.a1)).status_code, 405)

    def test_anonymous_is_sent_to_login(self):
        r = self.client.post(self.reassign_url(self.a1), {"assignee": ""})
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_other_org_gets_404(self):
        self.login(self.outsider)
        r = self.client.post(self.reassign_url(self.a1), {"assignee": ""})
        self.assertEqual(r.status_code, 404)

    def test_wrong_project_in_url_gets_404(self):
        self.login(self.admin)
        r = self.client.post(self.reassign_url(self.a1, project=self.pb), {"assignee": ""})
        self.assertEqual(r.status_code, 404)

    def test_archived_project_blocks_reassign(self):
        self.pa.archive()
        self.login(self.admin)
        self.client.post(self.reassign_url(self.a1), {"assignee": self.mate_p.pk})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.assignee_id, self.worker_p.pk)


class DeleteViewTests(StatusRouteBase):
    def test_admin_deletes_parent_and_subtasks_go_with_it(self):
        self.login(self.admin)
        r = self.client.post(self.delete_url(self.a1))
        self.assertRedirects(r, self.list_url(), fetch_redirect_response=False)
        self.assertFalse(Action.objects.filter(pk__in=[self.a1.pk, self.sub.pk]).exists())

    def test_deleting_subtask_keeps_parent(self):
        self.login(self.admin)
        self.client.post(self.delete_url(self.sub))
        self.assertFalse(Action.objects.filter(pk=self.sub.pk).exists())
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_assignee_cannot_delete(self):
        self.login(self.worker)
        r = self.client.post(self.delete_url(self.a1))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_plain_member_gets_403(self):
        self.login(self.mate)
        r = self.client.post(self.delete_url(self.a1))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_get_is_405(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.delete_url(self.a1)).status_code, 405)
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_anonymous_is_sent_to_login(self):
        r = self.client.post(self.delete_url(self.a1))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_other_org_gets_404(self):
        self.login(self.outsider)
        r = self.client.post(self.delete_url(self.a1))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_wrong_project_in_url_gets_404(self):
        self.login(self.admin)
        r = self.client.post(self.delete_url(self.a1, project=self.pb))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())

    def test_archived_project_blocks_delete(self):
        self.pa.archive()
        self.login(self.admin)
        self.client.post(self.delete_url(self.a1))
        self.assertTrue(Action.objects.filter(pk=self.a1.pk).exists())


class ManagePanelTests(StatusRouteBase):
    def test_admin_sees_all_controls(self):
        self.login(self.admin)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "Save status")
        self.assertContains(r, "Save assignee")
        self.assertContains(r, "Delete action")
        self.assertContains(r, "and its 1 subtask")

    def test_assignee_sees_status_only(self):
        self.login(self.worker)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "Save status")
        self.assertNotContains(r, "Save assignee")
        self.assertNotContains(r, "Delete action")

    def test_plain_member_sees_no_controls(self):
        self.login(self.mate)
        r = self.client.get(self.detail_url(self.a1))
        self.assertNotContains(r, "Save status")
        self.assertNotContains(r, "Save assignee")
        self.assertNotContains(r, "Delete action")

    def test_archived_project_shows_no_controls(self):
        self.pa.archive()
        self.login(self.admin)
        r = self.client.get(self.detail_url(self.a1))
        self.assertNotContains(r, "Save status")
        self.assertNotContains(r, "Save assignee")
        self.assertNotContains(r, "Delete action")
