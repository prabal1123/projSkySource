import io

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from app_projects.models import Project
from app_projects.test_views import ViewBase
from appEmp.models import EmployeeImportFieldConfig, empProfile as P

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADER = ("Full Name", "Email", "Project Code")


class ImportBase(ViewBase):
    def setUp(self):
        EmployeeImportFieldConfig.objects.filter(organization=self.org1).delete()
        EmployeeImportFieldConfig.objects.create(
            organization=self.org1, field_key="full_name", column_label="Full Name",
            display_name="Full Name", target_model="USER", data_type="FULL_NAME",
            is_required=True, order=1,
        )
        EmployeeImportFieldConfig.objects.create(
            organization=self.org1, field_key="email", column_label="Email",
            display_name="Email", target_model="USER", data_type="EMAIL",
            is_required=True, order=2,
        )
        self.client.force_login(self.su)
        session = self.client.session
        session["switched_org_id"] = self.org1.id
        session.save()

    @property
    def url(self):
        return reverse("employeeBulkImport")

    def sheet(self, rows, header=HEADER):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(list(header))
        for row in rows:
            worksheet.append(list(row))
        buffer = io.BytesIO()
        workbook.save(buffer)
        return SimpleUploadedFile("people.xlsx", buffer.getvalue(), content_type=XLSX)

    def preview(self, rows, header=HEADER, **extra):
        data = {"file": self.sheet(rows, header)}
        data.update(extra)
        return self.client.post(self.url, data)

    def confirm(self):
        return self.client.post(self.url, {"action": "confirm_import"})

    def notes(self, response):
        return [message.message for message in get_messages(response.wsgi_request)]

    def imported(self, email):
        return P.objects.filter(user__email=email).first()


class ImportCodeTests(ImportBase):
    def test_code_is_applied(self):
        self.preview([("Ann One", "zz_i1@example.com", "AL")])
        self.confirm()
        self.assertEqual(self.imported("zz_i1@example.com").project_id, self.pa.pk)

    def test_code_is_case_and_space_insensitive(self):
        self.preview([
            ("Ann One", "zz_i2@example.com", "al"),
            ("Bob Two", "zz_i3@example.com", "  Be "),
        ])
        self.confirm()
        self.assertEqual(self.imported("zz_i2@example.com").project_id, self.pa.pk)
        self.assertEqual(self.imported("zz_i3@example.com").project_id, self.pb.pk)

    def test_numeric_code_cell(self):
        numeric = Project.objects.create(organization=self.org1, name="Site 101", code="101")
        self.preview([("Ann One", "zz_i4@example.com", 101)])
        self.confirm()
        self.assertEqual(self.imported("zz_i4@example.com").project_id, numeric.pk)

    def test_unknown_code_blocks_only_its_row(self):
        response = self.preview([
            ("Ann One", "zz_i5@example.com", "ZZZ"),
            ("Bob Two", "zz_i6@example.com", "AL"),
        ])
        self.assertContains(response, "Unknown project code")
        self.confirm()
        self.assertIsNone(self.imported("zz_i5@example.com"))
        self.assertEqual(self.imported("zz_i6@example.com").project_id, self.pa.pk)

    def test_archived_code_blocks_only_its_row(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        response = self.preview([
            ("Ann One", "zz_i7@example.com", "BE"),
            ("Bob Two", "zz_i8@example.com", "AL"),
        ])
        self.assertContains(response, "is archived")
        self.confirm()
        self.assertIsNone(self.imported("zz_i7@example.com"))
        self.assertIsNotNone(self.imported("zz_i8@example.com"))

    def test_code_of_another_organization_is_unknown(self):
        response = self.preview([("Ann One", "zz_i9@example.com", "GA")])
        self.assertContains(response, "Unknown project code")
        self.confirm()
        self.assertIsNone(self.imported("zz_i9@example.com"))

    def test_on_hold_code_is_allowed(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ON_HOLD)
        self.preview([("Ann One", "zz_j1@example.com", "BE")])
        self.confirm()
        self.assertEqual(self.imported("zz_j1@example.com").project_id, self.pb.pk)


class ImportDefaultTests(ImportBase):
    def test_default_applies_to_blank_rows(self):
        self.preview([("Ann One", "zz_d1@example.com", None)], default_project=str(self.pa.uuid))
        self.confirm()
        self.assertEqual(self.imported("zz_d1@example.com").project_id, self.pa.pk)

    def test_row_code_beats_the_default(self):
        self.preview([("Ann One", "zz_d2@example.com", "BE")], default_project=str(self.pa.uuid))
        self.confirm()
        self.assertEqual(self.imported("zz_d2@example.com").project_id, self.pb.pk)

    def test_mixed_rows_get_their_own_projects(self):
        self.preview([
            ("Ann One", "zz_d3@example.com", "AL"),
            ("Bob Two", "zz_d4@example.com", "BE"),
            ("Cy Three", "zz_d5@example.com", None),
        ])
        self.confirm()
        self.assertEqual(self.imported("zz_d3@example.com").project_id, self.pa.pk)
        self.assertEqual(self.imported("zz_d4@example.com").project_id, self.pb.pk)
        self.assertIsNone(self.imported("zz_d5@example.com").project_id)

    def test_default_from_another_organization_is_rejected(self):
        response = self.preview(
            [("Ann One", "zz_d6@example.com", None)], default_project=str(self.pc.uuid)
        )
        self.assertEqual(response.context["preview_rows"], [])
        self.assertIn("default_project", response.context["form"].errors)
        self.confirm()
        self.assertIsNone(self.imported("zz_d6@example.com"))

    def test_archived_default_is_rejected(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        response = self.preview(
            [("Ann One", "zz_d7@example.com", None)], default_project=str(self.pb.uuid)
        )
        self.assertEqual(response.context["preview_rows"], [])
        self.assertIn("default_project", response.context["form"].errors)

    def test_dropdown_lists_only_open_projects_of_this_organization(self):
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        response = self.client.get(self.url)
        queryset = response.context["form"].fields["default_project"].queryset
        self.assertEqual(set(queryset), {self.pa})


class ImportConfirmTests(ImportBase):
    def test_project_archived_between_preview_and_confirm(self):
        self.preview([
            ("Ann One", "zz_c1@example.com", "BE"),
            ("Bob Two", "zz_c2@example.com", "AL"),
        ])
        Project.objects.filter(pk=self.pb.pk).update(status=Project.STATUS_ARCHIVED)
        response = self.confirm()
        self.assertIsNone(self.imported("zz_c1@example.com"))
        self.assertEqual(self.imported("zz_c2@example.com").project_id, self.pa.pk)
        self.assertTrue(any("no longer available" in text for text in self.notes(response)))

    def test_import_without_project_input_behaves_as_before(self):
        response = self.preview(
            [("Ann One", "zz_c3@example.com")], header=("Full Name", "Email")
        )
        self.assertFalse(response.context["show_project_column"])
        self.assertNotContains(response, "<th>Project</th>")
        self.confirm()
        self.assertIsNone(self.imported("zz_c3@example.com").project_id)


class ImportAccessTests(ImportBase):
    def test_member_cannot_open_the_import_page(self):
        self.client.force_login(self.person(self.org1, "zz_imem@example.com"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
