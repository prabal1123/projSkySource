from io import StringIO

from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, TestCase

from app_organizations.entitlements import grant_modules
from app_organizations.models import Organization, OrganizationMember
from app_organizations.seed import (
    ORG_ADMIN_GROUP,
    ORG_ADMIN_PERMISSIONS,
    ensure_org_admin_group,
)
from app_projects import access
from app_projects.models import Project
from appEmp.models import empProfile as P

PROJECT_CODENAMES = {"view_all_projects", "manage_projects"}


class AccessBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.bulk_create([
            User(username="zz_su", email="zz_su@example.com", is_staff=True, is_superuser=True, password="!")
        ])
        cls.su = User.objects.get(username="zz_su")
        cls.org1 = Organization.objects.create(name="ZZ Org One", created_by=cls.su)
        cls.org2 = Organization.objects.create(name="ZZ Org Two", created_by=cls.su)
        grant_modules(cls.org1)
        grant_modules(cls.org2)
        cls.pa = Project.objects.create(organization=cls.org1, name="Alpha", code="AL")
        cls.pb = Project.objects.create(organization=cls.org1, name="Beta", code="BE")
        cls.pc = Project.objects.create(organization=cls.org2, name="Gamma", code="GA")

    def make(self, org, email, **fields):
        user = User(username=email, email=email, first_name="Zz", last_name="Test")
        user.set_unusable_password()
        user._organization = org
        user.save()
        profile = P.objects.get(user=user)
        if fields:
            for key, value in fields.items():
                setattr(profile, key, value)
            profile.save()
        return profile

    def person(self, org, email, role="member", perms=(), project=None):
        fields = {"project": project} if project is not None else {}
        profile = self.make(org, email, **fields)
        OrganizationMember.objects.filter(user_id=profile.user_id).update(role=role)
        user = User.objects.get(pk=profile.user_id)
        for codename in perms:
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="app_projects", codename=codename
                )
            )
        return User.objects.get(pk=user.pk)

    def req(self, user, org):
        request = RequestFactory().get("/")
        request.user = user
        request.current_org = org
        return request

    def seen(self, user, org):
        return set(access.visible_projects(self.req(user, org)))


class VisibilityTests(AccessBase):
    def test_superuser_sees_every_project_of_the_current_org_only(self):
        self.assertEqual(self.seen(self.su, self.org1), {self.pa, self.pb})
        self.assertEqual(self.seen(self.su, self.org2), {self.pc})

    def test_owner_admin_manager_see_all_in_own_org_only(self):
        for role in ("owner", "admin", "manager"):
            user = self.person(self.org1, "zz_" + role + "@example.com", role=role)
            self.assertEqual(self.seen(user, self.org1), {self.pa, self.pb}, role)
            self.assertEqual(self.seen(user, self.org2), set(), role)

    def test_permission_holder_sees_all_in_own_org(self):
        user = self.person(self.org1, "zz_perm@example.com", perms=["view_all_projects"])
        self.assertEqual(self.seen(user, self.org1), {self.pa, self.pb})

    def test_permission_does_not_work_in_another_org(self):
        user = self.person(self.org1, "zz_perm2@example.com", perms=["view_all_projects"])
        self.assertEqual(self.seen(user, self.org2), set())

    def test_member_sees_only_own_project(self):
        user = self.person(self.org1, "zz_mem@example.com", project=self.pa)
        self.assertEqual(self.seen(user, self.org1), {self.pa})

    def test_member_without_project_sees_nothing(self):
        user = self.person(self.org1, "zz_none@example.com")
        self.assertEqual(self.seen(user, self.org1), set())

    def test_inactive_member_sees_nothing(self):
        user = self.person(self.org1, "zz_inactive@example.com", project=self.pa)
        P.objects.filter(user=user).update(is_active=False)
        self.assertEqual(self.seen(user, self.org1), set())

    def test_no_current_org_sees_nothing(self):
        user = self.person(self.org1, "zz_noorg@example.com", role="owner")
        self.assertEqual(self.seen(user, None), set())
        self.assertEqual(self.seen(self.su, None), set())

    def test_anonymous_sees_nothing(self):
        self.assertEqual(self.seen(AnonymousUser(), self.org1), set())


class DetailLookupTests(AccessBase):
    def test_member_can_open_own_project(self):
        user = self.person(self.org1, "zz_open@example.com", project=self.pa)
        found = access.get_visible_project_or_404(self.req(user, self.org1), self.pa.uuid)
        self.assertEqual(found, self.pa)

    def test_member_cannot_open_other_project_in_same_org(self):
        user = self.person(self.org1, "zz_other@example.com", project=self.pa)
        with self.assertRaises(Http404):
            access.get_visible_project_or_404(self.req(user, self.org1), self.pb.uuid)

    def test_project_of_another_org_is_a_404_even_for_owner(self):
        owner = self.person(self.org1, "zz_owner_x@example.com", role="owner")
        with self.assertRaises(Http404):
            access.get_visible_project_or_404(self.req(owner, self.org1), self.pc.uuid)

    def test_malformed_uuid_is_a_404(self):
        owner = self.person(self.org1, "zz_owner_y@example.com", role="owner")
        with self.assertRaises(Http404):
            access.get_visible_project_or_404(self.req(owner, self.org1), "not-a-uuid")


class ManageTests(AccessBase):
    def test_roles_that_can_manage(self):
        for role in ("owner", "admin", "manager"):
            user = self.person(self.org1, "zz_m_" + role + "@example.com", role=role)
            self.assertTrue(access.can_manage_projects(user, self.org1), role)

    def test_plain_member_cannot_manage(self):
        user = self.person(self.org1, "zz_plain@example.com", project=self.pa)
        self.assertFalse(access.can_manage_projects(user, self.org1))
        self.assertFalse(access.can_view_all_projects(user, self.org1))

    def test_manage_permission_lets_a_member_manage(self):
        user = self.person(self.org1, "zz_mp@example.com", perms=["manage_projects"])
        self.assertTrue(access.can_manage_projects(user, self.org1))
        self.assertFalse(access.can_manage_projects(user, self.org2))

    def test_superuser_can_manage_but_only_with_an_org(self):
        self.assertTrue(access.can_manage_projects(self.su, self.org1))
        self.assertFalse(access.can_manage_projects(self.su, None))

    def test_anonymous_cannot_manage(self):
        self.assertFalse(access.can_manage_projects(AnonymousUser(), self.org1))


class GroupSeedTests(AccessBase):
    def test_org_admin_group_keeps_project_permissions(self):
        group = ensure_org_admin_group()
        codenames = set(group.permissions.values_list("codename", flat=True))
        self.assertEqual(codenames, set(ORG_ADMIN_PERMISSIONS) | PROJECT_CODENAMES)

    def test_sync_adds_project_permissions_and_keeps_the_rest(self):
        app_perms = list(
            Permission.objects.filter(
                content_type__app_label="appEmp", codename__in=ORG_ADMIN_PERMISSIONS
            )
        )
        org_admin, _ = Group.objects.get_or_create(name=ORG_ADMIN_GROUP)
        org_admin.permissions.set(app_perms)
        hr, _ = Group.objects.get_or_create(name="HR_ADMIN")
        hr.permissions.set(app_perms[:1])

        for _run in range(2):
            call_command("sync_project_permissions", stdout=StringIO())

        org_codes = set(org_admin.permissions.values_list("codename", flat=True))
        self.assertEqual(org_codes, set(ORG_ADMIN_PERMISSIONS) | PROJECT_CODENAMES)
        hr_codes = set(hr.permissions.values_list("codename", flat=True))
        self.assertEqual(hr_codes, {app_perms[0].codename} | PROJECT_CODENAMES)

    def test_sync_skips_a_missing_group(self):
        Group.objects.filter(name="HR_ADMIN").delete()
        out = StringIO()
        call_command("sync_project_permissions", stdout=out)
        self.assertIn("HR_ADMIN: group not found", out.getvalue())
        self.assertFalse(Group.objects.filter(name="HR_ADMIN").exists())
