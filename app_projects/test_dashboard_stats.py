import datetime

from django.utils import timezone

from app_projects.models import Action
from app_projects.test_action_views import ActionViewBase
from appEmp.dashboard_stats import project_overview
from appEmp.models import empProfile


class ProjectOverviewTests(ActionViewBase):
    def overview(self, org=None):
        return project_overview(org or self.pa.organization, timezone.localdate())

    def row(self, data, name):
        return next(r for r in data["rows"] if r["name"] == name)

    def test_only_own_org_projects(self):
        names = {r["name"] for r in self.overview()["rows"]}
        self.assertIn(self.pa.name, names)
        self.assertNotIn(self.pc.name, names)

    def test_people_and_open_counts(self):
        expected = empProfile.objects.filter(project=self.pa, is_active=True).count()
        row = self.row(self.overview(), self.pa.name)
        self.assertEqual(row["people"], expected)
        self.assertEqual(row["open"], 3)
        self.assertEqual(row["overdue"], 0)

    def test_overdue_counted_and_done_ignored(self):
        past = timezone.localdate() - datetime.timedelta(days=3)
        Action.objects.filter(pk=self.a2.pk).update(due_date=past)
        self.assertEqual(self.row(self.overview(), self.pa.name)["overdue"], 1)
        Action.objects.filter(pk=self.a2.pk).update(status=Action.STATUS_DONE)
        row = self.row(self.overview(), self.pa.name)
        self.assertEqual(row["overdue"], 0)
        self.assertEqual(row["open"], 2)

    def test_archived_project_is_hidden(self):
        self.pb.archive()
        names = {r["name"] for r in self.overview()["rows"]}
        self.assertNotIn(self.pb.name, names)

    def test_unassigned_people_counted(self):
        self.assertGreaterEqual(self.overview()["unassigned"], 1)
