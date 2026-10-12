from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory
from django.urls import reverse

from app_projects.context_processors import project_nav
from app_projects.models import Project
from app_projects.test_access import AccessBase


class ViewBase(AccessBase):
    def login(self, user):
        self.client.force_login(user)

    def owner(self, org=None, email="zz_vowner@example.com"):
        return self.person(org or self.org1, email, role="owner")

    def data(self, **over):
        data = {
            "name": "Delta", "code": "dl", "description": "d", "status": "active",
            "lead": "", "start_date": "", "end_date": "",
        }
        data.update(over)
        return data


class ListViewTests(ViewBase):
    def test_anonymous_is_sent_to_login(self):
        r = self.client.get(reverse("projectList"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])

    def test_user_without_profile_gets_403(self):
        User.objects.bulk_create([User(username="zz_np", email="zz_np@example.com", password="!")])
        self.client.force_login(User.objects.get(username="zz_np"))
        self.assertEqual(self.client.get(reverse("projectList")).status_code, 403)

    def test_owner_sees_own_org_projects_only(self):
        self.login(self.owner())
        r = self.client.get(reverse("projectList"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alpha")
        self.assertContains(r, "Beta")
        self.assertNotContains(r, "Gamma")

    def test_archived_hidden_by_default_and_shown_on_request(self):
        self.pb.archive()
        self.login(self.owner())
        r = self.client.get(reverse("projectList"))
        self.assertContains(r, "Alpha")
        self.assertNotContains(r, "Beta")
        r = self.client.get(reverse("projectList") + "?show_archived=1")
        self.assertContains(r, "Beta")

    def test_search_by_name_and_code(self):
        self.login(self.owner())
        r = self.client.get(reverse("projectList") + "?q=alp")
        self.assertContains(r, "Alpha")
        self.assertNotContains(r, "Beta")
        r = self.client.get(reverse("projectList") + "?q=be")
        self.assertContains(r, "Beta")
        self.assertNotContains(r, "Alpha")

    def test_member_sees_only_own_project(self):
        self.login(self.person(self.org1, "zz_vmem@example.com", project=self.pa))
        r = self.client.get(reverse("projectList"))
        self.assertContains(r, "Alpha")
        self.assertNotContains(r, "Beta")

    def test_member_with_own_archived_project_still_sees_it(self):
        self.pa.archive()
        self.login(self.person(self.org1, "zz_varch@example.com", project=self.pa))
        self.assertContains(self.client.get(reverse("projectList")), "Alpha")

    def test_member_without_project_sees_empty_message(self):
        self.login(self.person(self.org1, "zz_vnone@example.com"))
        r = self.client.get(reverse("projectList"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "not been assigned")

    def test_superuser_sees_the_organization_they_switched_into(self):
        self.login(self.su)
        session = self.client.session
        session["switched_org_id"] = self.org2.pk
        session.save()
        r = self.client.get(reverse("projectList"))
        self.assertContains(r, "Gamma")
        self.assertNotContains(r, "Alpha")


class DetailViewTests(ViewBase):
    def test_owner_can_open_a_project(self):
        self.login(self.owner())
        r = self.client.get(reverse("projectDetail", args=[self.pa.uuid]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alpha")

    def test_team_shows_names_only(self):
        self.make(self.org1, "zz_team@example.com", project=self.pa, phone_number="9876500002")
        self.login(self.owner())
        r = self.client.get(reverse("projectDetail", args=[self.pa.uuid]))
        self.assertContains(r, "Zz Test")
        self.assertNotContains(r, "9876500002")

    def test_member_can_open_own_project(self):
        self.login(self.person(self.org1, "zz_dmem@example.com", project=self.pa))
        self.assertEqual(self.client.get(reverse("projectDetail", args=[self.pa.uuid])).status_code, 200)

    def test_member_cannot_open_other_project_in_same_org(self):
        self.login(self.person(self.org1, "zz_dother@example.com", project=self.pa))
        self.assertEqual(self.client.get(reverse("projectDetail", args=[self.pb.uuid])).status_code, 404)

    def test_project_of_another_org_is_404_even_for_owner(self):
        self.login(self.owner())
        self.assertEqual(self.client.get(reverse("projectDetail", args=[self.pc.uuid])).status_code, 404)

    def test_manage_buttons_only_for_managers(self):
        self.login(self.person(self.org1, "zz_dbtn@example.com", project=self.pa))
        r = self.client.get(reverse("projectDetail", args=[self.pa.uuid]))
        self.assertNotContains(r, reverse("projectEdit", args=[self.pa.uuid]))
        self.login(self.owner())
        r = self.client.get(reverse("projectDetail", args=[self.pa.uuid]))
        self.assertContains(r, reverse("projectEdit", args=[self.pa.uuid]))


class CreateViewTests(ViewBase):
    def test_member_gets_403_on_get_and_post(self):
        self.login(self.person(self.org1, "zz_cmem@example.com", project=self.pa))
        self.assertEqual(self.client.get(reverse("projectCreate")).status_code, 403)
        r = self.client.post(reverse("projectCreate"), self.data())
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Project.objects.filter(name="Delta").exists())

    def test_owner_creates_project_in_own_org_and_code_is_upper_cased(self):
        self.login(self.owner())
        r = self.client.post(reverse("projectCreate"), self.data())
        self.assertEqual(r.status_code, 302)
        project = Project.objects.get(name="Delta")
        self.assertEqual(project.organization_id, self.org1.id)
        self.assertEqual(project.code, "DL")
        self.assertEqual(r["Location"], reverse("projectDetail", args=[project.uuid]))

    def test_posted_organization_is_ignored(self):
        self.login(self.owner())
        self.client.post(reverse("projectCreate"), self.data(organization=self.org2.pk))
        self.assertEqual(Project.objects.get(name="Delta").organization_id, self.org1.id)

    def test_duplicate_name_is_rejected_case_insensitively(self):
        self.login(self.owner())
        r = self.client.post(reverse("projectCreate"), self.data(name="alpha", code="ZZ"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already exists")
        self.assertEqual(Project.objects.filter(organization=self.org1, name__iexact="alpha").count(), 1)

    def test_duplicate_code_is_rejected(self):
        self.login(self.owner())
        r = self.client.post(reverse("projectCreate"), self.data(code="al"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already exists")
        self.assertFalse(Project.objects.filter(name="Delta").exists())

    def test_same_name_is_fine_in_another_org(self):
        self.login(self.owner(self.org2, "zz_vowner2@example.com"))
        r = self.client.post(reverse("projectCreate"), self.data(name="Alpha", code="AL"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Project.objects.filter(organization=self.org2, name="Alpha").exists())

    def test_lead_from_another_org_is_rejected(self):
        foreign = self.make(self.org2, "zz_vlead@example.com")
        self.login(self.owner())
        r = self.client.post(reverse("projectCreate"), self.data(lead=foreign.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Project.objects.filter(name="Delta").exists())

    def test_end_date_before_start_is_rejected(self):
        self.login(self.owner())
        r = self.client.post(
            reverse("projectCreate"),
            self.data(start_date="2026-05-01", end_date="2026-04-01"),
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "End date cannot be before the start date.")
        self.assertFalse(Project.objects.filter(name="Delta").exists())


class EditViewTests(ViewBase):
    def test_owner_can_edit_and_keep_own_name(self):
        self.login(self.owner())
        r = self.client.post(
            reverse("projectEdit", args=[self.pa.uuid]),
            self.data(name="Alpha", code="AL", description="changed"),
        )
        self.assertEqual(r.status_code, 302)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.description, "changed")

    def test_edit_cannot_take_another_projects_name(self):
        self.login(self.owner())
        r = self.client.post(
            reverse("projectEdit", args=[self.pa.uuid]),
            self.data(name="Beta", code="AL"),
        )
        self.assertEqual(r.status_code, 200)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.name, "Alpha")

    def test_member_gets_403_even_on_own_project(self):
        self.login(self.person(self.org1, "zz_emem@example.com", project=self.pa))
        self.assertEqual(self.client.get(reverse("projectEdit", args=[self.pa.uuid])).status_code, 403)
        r = self.client.post(reverse("projectEdit", args=[self.pa.uuid]), self.data(name="Hacked", code="AL"))
        self.assertEqual(r.status_code, 403)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.name, "Alpha")

    def test_member_gets_404_for_a_project_they_cannot_see(self):
        self.login(self.person(self.org1, "zz_emem2@example.com", project=self.pa))
        self.assertEqual(self.client.get(reverse("projectEdit", args=[self.pb.uuid])).status_code, 404)

    def test_project_of_another_org_is_404(self):
        self.login(self.owner())
        self.assertEqual(self.client.get(reverse("projectEdit", args=[self.pc.uuid])).status_code, 404)
        r = self.client.post(reverse("projectEdit", args=[self.pc.uuid]), self.data(name="Hacked", code="GA"))
        self.assertEqual(r.status_code, 404)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.name, "Gamma")

    def test_archived_project_cannot_be_edited(self):
        self.pa.archive()
        self.login(self.owner())
        r = self.client.post(reverse("projectEdit", args=[self.pa.uuid]), self.data(name="Changed", code="AL"))
        self.assertEqual(r.status_code, 302)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.name, "Alpha")


class ArchiveViewTests(ViewBase):
    def test_post_archives_and_post_unarchives(self):
        self.login(self.owner())
        r = self.client.post(reverse("projectArchive", args=[self.pa.uuid]))
        self.assertEqual(r.status_code, 302)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.status, Project.STATUS_ARCHIVED)
        self.client.post(reverse("projectUnarchive", args=[self.pa.uuid]))
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.status, Project.STATUS_ACTIVE)

    def test_get_does_not_archive(self):
        self.login(self.owner())
        self.assertEqual(self.client.get(reverse("projectArchive", args=[self.pa.uuid])).status_code, 405)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.status, Project.STATUS_ACTIVE)

    def test_member_gets_403(self):
        self.login(self.person(self.org1, "zz_amem@example.com", project=self.pa))
        r = self.client.post(reverse("projectArchive", args=[self.pa.uuid]))
        self.assertEqual(r.status_code, 403)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.status, Project.STATUS_ACTIVE)

    def test_project_of_another_org_is_404(self):
        self.login(self.owner())
        self.assertEqual(self.client.post(reverse("projectArchive", args=[self.pc.uuid])).status_code, 404)
        self.pc.refresh_from_db()
        self.assertEqual(self.pc.status, Project.STATUS_ACTIVE)

    def test_archiving_keeps_employees_attached(self):
        emp = self.make(self.org1, "zz_aemp@example.com", project=self.pa)
        self.login(self.owner())
        self.client.post(reverse("projectArchive", args=[self.pa.uuid]))
        emp.refresh_from_db()
        self.assertEqual(emp.project_id, self.pa.id)


class NavTests(ViewBase):
    def nav(self, user, org):
        request = RequestFactory().get("/")
        request.user = user
        request.current_org = org
        return project_nav(request)

    def test_owner_sees_the_full_entry(self):
        nav = self.nav(self.owner(), self.org1)
        self.assertTrue(nav["projects_nav_show"])
        self.assertTrue(nav["projects_nav_all"])

    def test_member_with_project_sees_my_project(self):
        nav = self.nav(self.person(self.org1, "zz_nmem@example.com", project=self.pa), self.org1)
        self.assertTrue(nav["projects_nav_show"])
        self.assertFalse(nav["projects_nav_all"])

    def test_member_without_project_sees_nothing(self):
        nav = self.nav(self.person(self.org1, "zz_nnone@example.com"), self.org1)
        self.assertFalse(nav["projects_nav_show"])

    def test_anonymous_and_missing_org_see_nothing(self):
        self.assertFalse(self.nav(AnonymousUser(), self.org1)["projects_nav_show"])
        self.assertFalse(self.nav(self.owner(), None)["projects_nav_show"])

    def test_sidebar_is_rendered_for_the_right_people(self):
        self.login(self.owner())
        self.assertContains(self.client.get(reverse("projectList")), 'data-nav="projects"')
        self.login(self.person(self.org1, "zz_smem@example.com", project=self.pa))
        r = self.client.get(reverse("projectList"))
        self.assertContains(r, 'data-nav="projects"')
        self.assertContains(r, "My Project")
        self.login(self.person(self.org1, "zz_snone@example.com"))
        self.assertNotContains(self.client.get(reverse("projectList")), 'data-nav="projects"')
