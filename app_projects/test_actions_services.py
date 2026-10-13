from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from app_projects import services
from app_projects.models import Action
from app_projects.test_access import AccessBase
from appEmp.models import empProfile


class ActionBase(AccessBase):
    def setUp(self):
        self.admin = self.person(self.org1, "zz_aadmin@example.com", role="admin")
        self.worker = self.person(self.org1, "zz_aworker@example.com", project=self.pa)
        self.mate = self.person(self.org1, "zz_amate@example.com", project=self.pa)
        self.stranger = self.person(
            self.org2, "zz_astranger@example.com", role="admin", project=self.pc
        )
        self.worker_p = empProfile.objects.get(user=self.worker)
        self.mate_p = empProfile.objects.get(user=self.mate)
        self.stranger_p = empProfile.objects.get(user=self.stranger)

    def new(self, **over):
        kw = {
            "project": self.pa,
            "actor": self.admin,
            "title": "Write report",
            "assignee": self.worker_p,
        }
        kw.update(over)
        return services.create_action(**kw)


class CreateTests(ActionBase):
    def test_admin_creates_action_with_org_uuid_and_event(self):
        a = self.new()
        self.assertEqual(a.organization_id, self.org1.id)
        self.assertEqual(a.status, "todo")
        self.assertIsNotNone(a.uuid)
        self.assertEqual(list(a.events.values_list("kind", flat=True)), ["created"])

    def test_plain_member_cannot_create(self):
        with self.assertRaises(PermissionDenied):
            self.new(actor=self.worker)

    def test_admin_of_another_org_cannot_create(self):
        with self.assertRaises(PermissionDenied):
            self.new(actor=self.stranger)

    def test_assignee_must_be_on_the_project(self):
        outside = self.make(self.org1, "zz_aoutside@example.com", project=self.pb)
        with self.assertRaises(ValidationError):
            self.new(assignee=outside)

    def test_assignee_from_another_org_rejected(self):
        with self.assertRaises(ValidationError):
            self.new(assignee=self.stranger_p)

    def test_inactive_assignee_rejected(self):
        empProfile.objects.filter(pk=self.mate_p.pk).update(is_active=False)
        self.mate_p.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.new(assignee=self.mate_p)

    def test_archived_project_is_read_only(self):
        self.pa.archive()
        with self.assertRaises(ValidationError):
            self.new()

    def test_blank_and_overlong_titles_rejected(self):
        for title in ("   ", "x" * 201):
            with self.assertRaises(ValidationError):
                self.new(title=title)

    def test_model_rejects_project_from_another_org(self):
        with self.assertRaises(ValidationError):
            Action.objects.create(organization=self.org2, project=self.pa, title="x")


class SubtaskTests(ActionBase):
    def test_subtask_in_same_project(self):
        parent = self.new()
        child = self.new(title="Part 1", parent=parent)
        self.assertTrue(child.is_subtask)
        self.assertEqual(list(parent.subtasks.all()), [child])

    def test_subtask_of_subtask_rejected(self):
        parent = self.new()
        child = self.new(title="Part 1", parent=parent)
        with self.assertRaises(ValidationError):
            self.new(title="Part 1a", parent=child)

    def test_parent_from_another_project_rejected(self):
        parent = self.new()
        with self.assertRaises(ValidationError):
            self.new(project=self.pb, assignee=None, parent=parent)

    def test_parent_cannot_be_itself_at_database_level(self):
        a = self.new()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Action.objects.filter(pk=a.pk).update(parent=a)


class StatusTests(ActionBase):
    def test_assignee_moves_status_and_done_sets_completed_at(self):
        a = self.new()
        services.change_status(a, "in_progress", self.worker)
        services.change_status(a, "done", self.worker)
        a.refresh_from_db()
        self.assertEqual(a.status, "done")
        self.assertIsNotNone(a.completed_at)
        services.change_status(a, "todo", self.admin)
        a.refresh_from_db()
        self.assertIsNone(a.completed_at)
        self.assertEqual(
            list(a.events.values_list("kind", flat=True)),
            ["created", "status", "status", "status"],
        )

    def test_other_team_member_cannot_change_status(self):
        a = self.new()
        with self.assertRaises(PermissionDenied):
            services.change_status(a, "done", self.mate)

    def test_invalid_status_rejected(self):
        a = self.new()
        for bad in ("abc", "", None, ["done"]):
            with self.assertRaises(ValidationError):
                services.change_status(a, bad, self.admin)

    def test_same_status_writes_no_event(self):
        a = self.new()
        services.change_status(a, "todo", self.admin)
        self.assertEqual(a.events.count(), 1)

    def test_archived_project_blocks_status_change(self):
        a = self.new()
        self.pa.archive()
        with self.assertRaises(ValidationError):
            services.change_status(a, "done", self.admin)


class ReassignEditDeleteTests(ActionBase):
    def test_reassign_and_unassign(self):
        a = self.new()
        services.reassign(a, self.mate_p, self.admin)
        a.refresh_from_db()
        self.assertEqual(a.assignee_id, self.mate_p.pk)
        services.reassign(a, None, self.admin)
        a.refresh_from_db()
        self.assertIsNone(a.assignee_id)
        self.assertEqual(a.events.filter(kind="assignee").count(), 2)

    def test_reassign_needs_manager(self):
        a = self.new()
        with self.assertRaises(PermissionDenied):
            services.reassign(a, self.mate_p, self.worker)

    def test_update_changes_fields_and_writes_one_event(self):
        a = self.new()
        services.update_action(a, self.admin, title="New title", description="Secret")
        a.refresh_from_db()
        self.assertEqual(a.title, "New title")
        self.assertEqual(a.events.filter(kind="edited").count(), 1)
        with self.assertRaises(ValidationError):
            services.update_action(a, self.admin, status="done")
        with self.assertRaises(PermissionDenied):
            services.update_action(a, self.worker, title="Hacked")

    def test_delete_needs_manager_and_removes_subtasks(self):
        parent = self.new()
        child = self.new(title="Part 1", parent=parent)
        with self.assertRaises(PermissionDenied):
            services.delete_action(parent, self.worker)
        services.delete_action(parent, self.admin)
        self.assertFalse(Action.objects.filter(pk__in=[parent.pk, child.pk]).exists())


class IntegrityTests(ActionBase):
    def test_moved_or_deactivated_assignee_is_flagged_not_cleared(self):
        a = self.new()
        b = self.new(title="Other", assignee=self.mate_p)
        empProfile.objects.filter(pk=self.worker_p.pk).update(project=self.pb)
        empProfile.objects.filter(pk=self.mate_p.pk).update(is_active=False)
        self.assertEqual(
            {x.pk for x in services.actions_needing_reassign(self.pa)}, {a.pk, b.pk}
        )
        a.refresh_from_db()
        self.assertEqual(a.assignee_id, self.worker_p.pk)
        self.assertTrue(a.needs_reassign)

    def test_assignee_cannot_be_deleted(self):
        self.new()
        with self.assertRaises(ProtectedError):
            self.worker_p.delete()

    def test_description_is_encrypted_at_rest(self):
        a = self.new(description="Top secret plan")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT description FROM %s WHERE id = %%s" % Action._meta.db_table,
                [a.pk],
            )
            raw = cursor.fetchone()[0]
        self.assertNotIn("Top secret plan", raw)
        self.assertEqual(Action.objects.get(pk=a.pk).description, "Top secret plan")
