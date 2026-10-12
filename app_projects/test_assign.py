from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import reverse

from app_projects.context_processors import project_nav
from app_projects.models import Project
from app_projects.test_views import ViewBase
from appEmp.models import empProfile as P


class AssignBase(ViewBase):
    @property
    def url(self):
        return reverse("projectAssign")

    def emp(self, org, email, first="Zz", last="Test", project=None, active=True):
        fields = {"project": project} if project is not None else {}
        profile = self.make(org, email, **fields)
        User.objects.filter(pk=profile.user_id).update(first_name=first, last_name=last)
        if not active:
            P.objects.filter(pk=profile.pk).update(is_active=False)
        return P.objects.get(pk=profile.pk)

    def manager(self):
        return self.person(self.org1, "zz_amgr@example.com", role="manager")

    def member(self):
        return self.person(self.org1, "zz_amem@example.com", project=self.pa)

    def switched_superuser(self):
        self.client.force_login(self.su)
        session = self.client.session
        session["switched_org_id"] = self.org1.id
        session.save()

    def post(self, employees, target, follow=False, **extra):
        data = {"employees": [str(e.uuid) for e in employees], "target": str(target)}
        data.update(extra)
        return self.client.post(self.url, data, follow=follow)

    def project_of(self, employee):
        return P.objects.get(pk=employee.pk).project_id


class AssignAccessTests(AssignBase):
    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_member_gets_403(self):
        self.login(self.member())
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_superuser_without_an_organization_gets_403(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_owner_gets_200(self):
        self.login(self.owner())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_manager_gets_200(self):
        self.login(self.manager())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_switched_superuser_gets_200(self):
        self.switched_superuser()
        self.assertEqual(self.client.get(self.url).status_code, 200)


class AssignListTests(AssignBase):
    def test_lists_only_active_people_of_the_current_organization(self):
        self.emp(self.org1, "zz_l1@example.com", first="Alice", last="Aaa")
        self.emp(self.org2, "zz_l2@example.com", first="Bruno", last="Bbb")
        self.emp(self.org1, "zz_l3@example.com", first="Carol", last="Ccc", active=False)
        self.login(self.owner())
        response = self.client.get(self.url)
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bruno")
        self.assertNotContains(response, "Carol")

    def test_page_does_not_show_email_addresses(self):
        self.emp(self.org1, "zz_secret1@example.com", first="Alice", last="Aaa")
        self.login(self.owner())
        self.assertNotContains(self.client.get(self.url), "zz_secret1@example.com")

    def test_unnamed_employee_fallback_does_not_leak_the_email(self):
        self.emp(self.org1, "zz_secret2@example.com", first="", last="")
        self.login(self.owner())
        response = self.client.get(self.url)
        self.assertContains(response, "Unnamed employee")
        self.assertNotContains(response, "zz_secret2@example.com")

    def test_search_by_name(self):
        self.emp(self.org1, "zz_s1@example.com", first="Alice", last="Aaa")
        self.emp(self.org1, "zz_s2@example.com", first="Dave", last="Ddd")
        self.login(self.owner())
        response = self.client.get(self.url, {"q": "alice"})
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Dave")
        response = self.client.get(self.url, {"q": "alice aaa"})
        self.assertContains(response, "Alice")
        response = self.client.get(self.url, {"q": "aaa dave"})
        self.assertNotContains(response, "Alice")
        self.assertNotContains(response, "Dave")

    def test_unassigned_filter(self):
        self.emp(self.org1, "zz_u1@example.com", first="Alice", last="Aaa")
        self.emp(self.org1, "zz_u2@example.com", first="Bruno", last="Bbb", project=self.pa)
        self.login(self.owner())
        response = self.client.get(self.url, {"project": "unassigned"})
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bruno")

    def test_project_filter(self):
        self.emp(self.org1, "zz_p1@example.com", first="Alice", last="Aaa")
        self.emp(self.org1, "zz_p2@example.com", first="Bruno", last="Bbb", project=self.pa)
        self.login(self.owner())
        response = self.client.get(self.url, {"project": str(self.pa.uuid)})
        self.assertContains(response, "Bruno")
        self.assertNotContains(response, "Alice")

    def test_invalid_and_foreign_project_filters_are_ignored(self):
        self.emp(self.org1, "zz_i1@example.com", first="Alice", last="Aaa")
        self.emp(self.org1, "zz_i2@example.com", first="Bruno", last="Bbb", project=self.pa)
        self.login(self.owner())
        for value in ("abc", str(self.pc.uuid)):
            response = self.client.get(self.url, {"project": value})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Alice")
            self.assertContains(response, "Bruno")

    def test_bad_page_numbers_do_not_crash(self):
        self.login(self.owner())
        self.assertEqual(self.client.get(self.url, {"page": "999"}).status_code, 200)
        self.assertEqual(self.client.get(self.url, {"page": "abc"}).status_code, 200)

    def test_pagination_splits_after_fifty(self):
        for number in range(51):
            self.emp(self.org1, "zz_pg%d@example.com" % number, first="Pg%02d" % number, last="Test")
        self.login(self.owner())
        response = self.client.get(self.url)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["page_obj"]), 50)


class AssignPostTests(AssignBase):
    def setUp(self):
        self.login(self.owner())

    def test_assign_an_unassigned_person(self):
        e = self.emp(self.org1, "zz_a1@example.com")
        response = self.post([e], self.pa.uuid, follow=True)
        self.assertEqual(self.project_of(e), self.pa.pk)
        self.assertContains(response, "1 assigned")

    def test_move_between_projects(self):
        e = self.emp(self.org1, "zz_a2@example.com", project=self.pa)
        response = self.post([e], self.pb.uuid, follow=True)
        self.assertEqual(self.project_of(e), self.pb.pk)
        self.assertContains(response, "1 moved")

    def test_unassign(self):
        e = self.emp(self.org1, "zz_a3@example.com", project=self.pa)
        response = self.post([e], "none", follow=True)
        self.assertIsNone(self.project_of(e))
        self.assertContains(response, "1 unassigned")

    def test_same_project_is_left_alone(self):
        e = self.emp(self.org1, "zz_a4@example.com", project=self.pa)
        response = self.post([e], self.pa.uuid, follow=True)
        self.assertEqual(self.project_of(e), self.pa.pk)
        self.assertContains(response, "already in that project")

    def test_on_hold_project_accepts_people(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ON_HOLD)
        e = self.emp(self.org1, "zz_a5@example.com")
        self.post([e], self.pb.uuid)
        self.assertEqual(self.project_of(e), self.pb.pk)

    def test_archived_project_is_rejected(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        e = self.emp(self.org1, "zz_a6@example.com")
        response = self.post([e], self.pb.uuid, follow=True)
        self.assertIsNone(self.project_of(e))
        self.assertContains(response, "Choose a project")

    def test_project_of_another_organization_is_rejected(self):
        e = self.emp(self.org1, "zz_a7@example.com")
        response = self.post([e], self.pc.uuid, follow=True)
        self.assertIsNone(self.project_of(e))
        self.assertContains(response, "Choose a project")

    def test_employee_of_another_organization_is_ignored(self):
        foreign = self.emp(self.org2, "zz_a8@example.com", project=self.pc)
        response = self.post([foreign], self.pa.uuid, follow=True)
        self.assertEqual(self.project_of(foreign), self.pc.pk)
        self.assertContains(response, "could not be found")

    def test_inactive_employee_is_ignored(self):
        e = self.emp(self.org1, "zz_a9@example.com", active=False)
        response = self.post([e], self.pa.uuid, follow=True)
        self.assertIsNone(self.project_of(e))
        self.assertContains(response, "could not be found")

    def test_malformed_ids_are_skipped_without_a_server_error(self):
        e = self.emp(self.org1, "zz_b1@example.com")
        response = self.client.post(
            self.url,
            {"employees": ["abc", str(e.uuid)], "target": str(self.pa.uuid)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project_of(e), self.pa.pk)
        self.assertContains(response, "could not be found")

    def test_empty_selection_is_an_error(self):
        response = self.post([], self.pa.uuid, follow=True)
        self.assertContains(response, "Select at least one employee.")

    def test_missing_target_is_an_error(self):
        e = self.emp(self.org1, "zz_b2@example.com")
        response = self.post([e], "", follow=True)
        self.assertIsNone(self.project_of(e))
        self.assertContains(response, "Choose a project")

    def test_member_cannot_post(self):
        e = self.emp(self.org1, "zz_b3@example.com")
        self.login(self.member())
        response = self.post([e], self.pa.uuid)
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.project_of(e))

    def test_only_project_and_updated_at_change(self):
        e = self.emp(self.org1, "zz_b4@example.com")
        before = P.objects.filter(pk=e.pk).values().first()
        self.post([e], self.pa.uuid)
        after = P.objects.filter(pk=e.pk).values().first()
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {"project_id", "updated_at"})

    def test_redirect_keeps_only_the_known_filters(self):
        e = self.emp(self.org1, "zz_b5@example.com")
        response = self.post([e], self.pa.uuid, q="Alice", project="unassigned", page="2")
        self.assertRedirects(
            response,
            self.url + "?q=Alice&project=unassigned&page=2",
            fetch_redirect_response=False,
        )

    def test_redirect_ignores_other_parameters(self):
        e = self.emp(self.org1, "zz_b6@example.com")
        response = self.post([e], self.pa.uuid, next="http://evil.example/")
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_project_lead_is_not_changed_when_the_lead_moves(self):
        e = self.emp(self.org1, "zz_b7@example.com", project=self.pa)
        Project.objects.filter(pk=self.pa.pk).update(lead=e)
        self.post([e], self.pb.uuid)
        self.assertEqual(Project.objects.get(pk=self.pa.pk).lead_id, e.pk)


class AssignNavTests(AssignBase):
    def nav(self, user):
        request = RequestFactory().get("/")
        request.user = user
        request.current_org = self.org1
        return project_nav(request)

    def test_manage_flag(self):
        self.assertTrue(self.nav(self.owner())["projects_nav_manage"])
        self.assertTrue(self.nav(self.manager())["projects_nav_manage"])
        self.assertFalse(self.nav(self.member())["projects_nav_manage"])

    def test_link_is_shown_to_owner_and_manager(self):
        for user in (self.owner(), self.manager()):
            self.login(user)
            self.assertContains(self.client.get(reverse("projectList")), 'href="/projects/assign/"')

    def test_link_is_hidden_from_a_member(self):
        self.login(self.member())
        self.assertNotContains(self.client.get(reverse("projectList")), 'href="/projects/assign/"')

    def test_active_highlight_follows_the_page(self):
        self.login(self.owner())
        on_assign = self.client.get(self.url)
        self.assertContains(on_assign, 'data-nav="projects" class="hr-sidebar-link "')
        self.assertContains(on_assign, 'href="/projects/assign/" class="hr-sidebar-link active"')
        on_list = self.client.get(reverse("projectList"))
        self.assertContains(on_list, 'data-nav="projects" class="hr-sidebar-link active"')
