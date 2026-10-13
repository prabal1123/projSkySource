from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app_projects import services
from app_projects.models import Action
from app_projects.test_views import ViewBase
from appEmp.models import empProfile

ACTIVE_PROJECTS = 'data-nav="projects" class="hr-sidebar-link active"'
MY_ACTIVE = 'data-nav="my-actions" class="hr-sidebar-link active"'
MY_INACTIVE = 'data-nav="my-actions" class="hr-sidebar-link "'


class ActionViewBase(ViewBase):
    def setUp(self):
        self.admin = self.person(self.org1, "zz_vadmin@example.com", role="admin")
        self.worker = self.person(self.org1, "zz_vworker@example.com", project=self.pa)
        self.mate = self.person(self.org1, "zz_vmate@example.com", project=self.pa)
        self.beta_user = self.person(self.org1, "zz_vbeta@example.com", project=self.pb)
        self.outsider = self.person(
            self.org2, "zz_voutsider@example.com", role="admin", project=self.pc
        )
        self.worker_p = empProfile.objects.get(user=self.worker)
        self.mate_p = empProfile.objects.get(user=self.mate)
        self.beta_p = empProfile.objects.get(user=self.beta_user)
        self.outsider_p = empProfile.objects.get(user=self.outsider)

        self.a1 = services.create_action(
            project=self.pa, actor=self.admin, title="Alpha task",
            description="Secret text", assignee=self.worker_p,
        )
        self.a2 = services.create_action(
            project=self.pa, actor=self.admin, title="Beta chore"
        )
        self.sub = services.create_action(
            project=self.pa, actor=self.admin, title="Sub item", parent=self.a1
        )

    def list_url(self, project=None):
        return reverse("projectActionList", args=[(project or self.pa).uuid])

    def detail_url(self, action, project=None):
        return reverse("projectActionDetail", args=[(project or self.pa).uuid, action.uuid])

    def edit_url(self, action, project=None):
        return reverse("projectActionEdit", args=[(project or self.pa).uuid, action.uuid])

    def create_url(self, project=None):
        return reverse("projectActionCreate", args=[(project or self.pa).uuid])


class ActionListTests(ActionViewBase):
    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(self.list_url())
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_admin_sees_top_level_actions_only(self):
        self.login(self.admin)
        r = self.client.get(self.list_url())
        self.assertContains(r, "Alpha task")
        self.assertContains(r, "Beta chore")
        self.assertNotContains(r, "Sub item")
        self.assertContains(r, "1 subtask")

    def test_member_sees_list_without_add_button(self):
        self.login(self.mate)
        r = self.client.get(self.list_url())
        self.assertContains(r, "Alpha task")
        self.assertNotContains(r, "Add action")

    def test_member_of_another_project_gets_404(self):
        self.login(self.beta_user)
        self.assertEqual(self.client.get(self.list_url()).status_code, 404)

    def test_admin_of_another_org_gets_404(self):
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.list_url()).status_code, 404)

    def test_status_filter(self):
        services.change_status(self.a2, "done", self.admin)
        self.login(self.admin)
        r = self.client.get(self.list_url(), {"status": "done"})
        self.assertContains(r, "Beta chore")
        self.assertNotContains(r, "Alpha task")

    def test_junk_params_do_not_crash(self):
        self.login(self.admin)
        r = self.client.get(
            self.list_url(),
            {"status": "abc", "assignee": "abc", "q": "%\x00'", "page": "zzz"},
        )
        self.assertEqual(r.status_code, 200)

    def test_assignee_filter(self):
        self.login(self.admin)
        r = self.client.get(self.list_url(), {"assignee": str(self.worker_p.uuid)})
        self.assertContains(r, "Alpha task")
        self.assertNotContains(r, "Beta chore")
        r = self.client.get(self.list_url(), {"assignee": "unassigned"})
        self.assertContains(r, "Beta chore")
        self.assertNotContains(r, "Alpha task")

    def test_title_search_but_not_description_search(self):
        self.login(self.admin)
        r = self.client.get(self.list_url(), {"q": "chore"})
        self.assertContains(r, "Beta chore")
        self.assertNotContains(r, "Alpha task")
        r = self.client.get(self.list_url(), {"q": "Secret"})
        self.assertNotContains(r, "Alpha task")

    def test_archived_project_has_no_add_button(self):
        self.pa.archive()
        self.login(self.admin)
        r = self.client.get(self.list_url())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Add action")

    def test_query_count_does_not_grow_with_rows(self):
        self.login(self.admin)
        self.client.get(self.list_url())

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(self.list_url()).status_code, 200)
            return len(ctx)

        before = count()
        for i in range(5):
            services.create_action(
                project=self.pa, actor=self.admin, title="Extra %d" % i,
                assignee=self.worker_p,
            )
        self.assertEqual(count(), before)


class ActionDetailTests(ActionViewBase):
    def test_member_sees_detail_subtasks_and_history(self):
        self.login(self.mate)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "Secret text")
        self.assertContains(r, "Sub item")
        self.assertContains(r, "Created as To do")

    def test_action_under_the_wrong_project_is_404(self):
        other = services.create_action(project=self.pb, actor=self.admin, title="Beta only")
        self.login(self.admin)
        self.assertEqual(self.client.get(self.detail_url(other, self.pa)).status_code, 404)

    def test_admin_of_another_org_gets_404(self):
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.detail_url(self.a1)).status_code, 404)

    def test_needs_reassigning_badge_and_project_page_list(self):
        empProfile.objects.filter(pk=self.worker_p.pk).update(project=self.pb)
        self.login(self.admin)
        self.assertContains(self.client.get(self.detail_url(self.a1)), "Needs reassigning")
        r = self.client.get(reverse("projectDetail", args=[self.pa.uuid]))
        self.assertContains(r, "Needs reassigning (1)")


class ActionFormTests(ActionViewBase):
    def test_admin_creates_action(self):
        self.login(self.admin)
        r = self.client.post(self.create_url(), {
            "title": "New one", "description": "d",
            "assignee": self.worker_p.pk, "due_date": "2030-01-31",
        })
        self.assertEqual(r.status_code, 302)
        a = Action.objects.get(title="New one")
        self.assertEqual(a.assignee_id, self.worker_p.pk)
        self.assertEqual(a.created_by_id, self.admin.pk)

    def test_member_cannot_create(self):
        self.login(self.worker)
        self.assertEqual(self.client.get(self.create_url()).status_code, 403)
        r = self.client.post(self.create_url(), {"title": "Nope"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Action.objects.filter(title="Nope").exists())

    def test_assignee_from_another_org_rejected(self):
        self.login(self.admin)
        r = self.client.post(self.create_url(), {
            "title": "Leak", "assignee": self.outsider_p.pk,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Action.objects.filter(title="Leak").exists())

    def test_assignee_from_another_project_rejected(self):
        self.login(self.admin)
        r = self.client.post(self.create_url(), {
            "title": "Wrong team", "assignee": self.beta_p.pk,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Action.objects.filter(title="Wrong team").exists())

    def test_archived_project_blocks_create(self):
        self.pa.archive()
        self.login(self.admin)
        r = self.client.post(self.create_url(), {"title": "Late"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Action.objects.filter(title="Late").exists())

    def test_admin_edits_title_and_assignee(self):
        self.login(self.admin)
        r = self.client.post(self.edit_url(self.a1), {
            "title": "Renamed", "description": "New text",
            "assignee": self.mate_p.pk, "due_date": "",
        })
        self.assertEqual(r.status_code, 302)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.title, "Renamed")
        self.assertEqual(self.a1.assignee_id, self.mate_p.pk)
        kinds = set(self.a1.events.values_list("kind", flat=True))
        self.assertTrue({"edited", "assignee"} <= kinds)

    def test_blank_title_rejected_on_edit(self):
        self.login(self.admin)
        r = self.client.post(self.edit_url(self.a1), {
            "title": "  ", "assignee": self.worker_p.pk,
        })
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.title, "Alpha task")

    def test_member_cannot_edit(self):
        self.login(self.worker)
        self.assertEqual(self.client.get(self.edit_url(self.a1)).status_code, 403)
        r = self.client.post(self.edit_url(self.a1), {"title": "Hacked"})
        self.assertEqual(r.status_code, 403)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.title, "Alpha task")

    def test_edit_under_the_wrong_project_is_404(self):
        self.login(self.admin)
        r = self.client.get(self.edit_url(self.a1, self.pb))
        self.assertEqual(r.status_code, 404)


class MyActionsTests(ActionViewBase):
    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse("myActions"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_shows_only_own_open_actions(self):
        self.login(self.worker)
        r = self.client.get(reverse("myActions"))
        self.assertContains(r, "Alpha task")
        self.assertNotContains(r, "Beta chore")
        self.login(self.mate)
        self.assertNotContains(self.client.get(reverse("myActions")), "Alpha task")

    def test_done_toggle(self):
        services.change_status(self.a1, "done", self.admin)
        self.login(self.worker)
        self.assertNotContains(self.client.get(reverse("myActions")), "Alpha task")
        r = self.client.get(reverse("myActions"), {"done": "1"})
        self.assertContains(r, "Alpha task")

    def test_user_of_another_org_sees_nothing(self):
        self.login(self.outsider)
        r = self.client.get(reverse("myActions"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Alpha task")


class ActionNavTests(ActionViewBase):
    def test_my_actions_link_hook_and_active_state(self):
        self.login(self.worker)
        self.assertContains(self.client.get(reverse("myActions")), MY_ACTIVE)
        self.assertContains(self.client.get(reverse("projectList")), MY_INACTIVE)

    def test_link_hidden_without_a_project(self):
        self.login(self.person(self.org1, "zz_vnoproj@example.com"))
        r = self.client.get(reverse("projectList"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'data-nav="my-actions"')

    def test_projects_link_stays_active_on_action_pages(self):
        self.login(self.admin)
        self.assertContains(self.client.get(self.list_url()), ACTIVE_PROJECTS)
        self.assertContains(self.client.get(self.detail_url(self.a1)), ACTIVE_PROJECTS)
        self.assertNotContains(self.client.get(reverse("myActions")), ACTIVE_PROJECTS)
