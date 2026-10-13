import io
import os
import shutil
import tempfile
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.urls import reverse

from app_projects import services
from app_projects.models import Action, ActionAttachment, ActionComment
from app_projects.test_action_views import ActionViewBase


def pdf_file(name="a.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\nhello\n%%EOF", content_type="application/pdf")


def png_file(name="a.png"):
    return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\n" + b"0" * 20, content_type="image/png")


def jpg_file(name="a.jpg"):
    return SimpleUploadedFile(name, b"\xff\xd8\xff\xe0" + b"0" * 20, content_type="image/jpeg")


def docx_file(name="a.docx", with_word=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml" if with_word else "other.txt", "<w/>")
    return SimpleUploadedFile(name, buf.getvalue())


class ExtrasBase(ActionViewBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ctx = override_settings(PRIVATE_MEDIA_ROOT=self.tmp)
        ctx.enable()
        self.addCleanup(ctx.disable)

    def u(self, name, action, *extra, project=None):
        return reverse(name, args=[(project or self.pa).uuid, action.uuid, *extra])

    def stored(self, att):
        return os.path.join(self.tmp, att.file.name)


class SubtaskTests(ExtrasBase):
    def sub_data(self, **over):
        d = {"title": "Child task", "description": "", "assignee": "", "due_date": ""}
        d.update(over)
        return d

    def test_admin_creates_subtask_and_event_is_written(self):
        self.login(self.admin)
        url = self.u("projectActionSubtaskCreate", self.a2)
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, self.sub_data(assignee=self.mate_p.pk))
        self.assertRedirects(r, self.detail_url(self.a2), fetch_redirect_response=False)
        child = Action.objects.get(title="Child task")
        self.assertEqual(child.parent_id, self.a2.pk)
        self.assertEqual(child.project_id, self.pa.pk)
        self.assertEqual(child.assignee_id, self.mate_p.pk)
        self.assertEqual(child.events.count(), 1)

    def test_plain_member_gets_403(self):
        self.login(self.mate)
        url = self.u("projectActionSubtaskCreate", self.a2)
        before = Action.objects.count()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.sub_data()).status_code, 403)
        self.assertEqual(Action.objects.count(), before)

    def test_subtask_of_subtask_is_rejected(self):
        self.login(self.admin)
        before = Action.objects.count()
        r = self.client.post(self.u("projectActionSubtaskCreate", self.sub), self.sub_data())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Action.objects.count(), before)

    def test_assignee_from_other_project_is_rejected(self):
        self.login(self.admin)
        before = Action.objects.count()
        r = self.client.post(
            self.u("projectActionSubtaskCreate", self.a2), self.sub_data(assignee=self.beta_p.pk)
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Action.objects.count(), before)

    def test_anonymous_other_project_other_org_and_wrong_project(self):
        url = self.u("projectActionSubtaskCreate", self.a2)
        r = self.client.post(url, self.sub_data())
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])
        self.login(self.beta_user)
        self.assertEqual(self.client.post(url, self.sub_data()).status_code, 404)
        self.login(self.outsider)
        self.assertEqual(self.client.post(url, self.sub_data()).status_code, 404)
        self.login(self.admin)
        wrong = self.u("projectActionSubtaskCreate", self.a2, project=self.pb)
        self.assertEqual(self.client.post(wrong, self.sub_data()).status_code, 404)

    def test_archived_project_blocks_subtask(self):
        self.pa.archive()
        self.login(self.admin)
        before = Action.objects.count()
        self.client.post(self.u("projectActionSubtaskCreate", self.a2), self.sub_data())
        self.assertEqual(Action.objects.count(), before)

    def test_add_subtask_button_visibility(self):
        self.login(self.admin)
        self.assertContains(self.client.get(self.detail_url(self.a1)), "Add subtask")
        self.assertNotContains(self.client.get(self.detail_url(self.sub)), "Add subtask")
        self.login(self.mate)
        self.assertNotContains(self.client.get(self.detail_url(self.a1)), "Add subtask")


class CommentTests(ExtrasBase):
    def new_comment(self, user=None, body="First note", action=None):
        return services.add_comment(action or self.a1, user or self.worker, body)

    def test_member_adds_comment_and_sees_it(self):
        self.login(self.mate)
        r = self.client.post(self.u("projectActionCommentAdd", self.a1), {"body": "Looks good"})
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        c = ActionComment.objects.get()
        self.assertEqual((c.author_id, c.action_id, c.body), (self.mate.pk, self.a1.pk, "Looks good"))
        self.assertContains(self.client.get(self.detail_url(self.a1)), "Looks good")

    def test_body_is_encrypted_at_rest(self):
        self.login(self.mate)
        self.client.post(self.u("projectActionCommentAdd", self.a1), {"body": "Very private note"})
        with connection.cursor() as cur:
            cur.execute("select body from %s" % ActionComment._meta.db_table)
            raw = " ".join(str(row[0]) for row in cur.fetchall())
        self.assertTrue(raw)
        self.assertNotIn("Very private note", raw)

    def test_empty_whitespace_and_overlong_are_rejected(self):
        self.login(self.mate)
        url = self.u("projectActionCommentAdd", self.a1)
        for body in ("", "   ", "x" * 5001):
            self.client.post(url, {"body": body})
        self.assertEqual(ActionComment.objects.count(), 0)

    def test_add_get_is_405_and_access_rules(self):
        url = self.u("projectActionCommentAdd", self.a1)
        r = self.client.post(url, {"body": "hi"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])
        self.login(self.mate)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.login(self.beta_user)
        self.assertEqual(self.client.post(url, {"body": "hi"}).status_code, 404)
        self.login(self.outsider)
        self.assertEqual(self.client.post(url, {"body": "hi"}).status_code, 404)
        own = self.u("projectActionCommentAdd", self.a1, project=self.pc)
        self.assertEqual(self.client.post(own, {"body": "hi"}).status_code, 404)
        self.assertEqual(ActionComment.objects.count(), 0)

    def test_author_edits_own_comment(self):
        c = self.new_comment(self.worker)
        self.login(self.worker)
        url = self.u("projectActionCommentEdit", self.a1, c.uuid)
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"body": "Changed"})
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        c.refresh_from_db()
        self.assertEqual(c.body, "Changed")
        self.assertIsNotNone(c.edited_at)

    def test_other_member_cannot_edit_or_delete(self):
        c = self.new_comment(self.worker)
        self.login(self.mate)
        edit = self.u("projectActionCommentEdit", self.a1, c.uuid)
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.post(edit, {"body": "Hacked"}).status_code, 403)
        r = self.client.post(self.u("projectActionCommentDelete", self.a1, c.uuid))
        self.assertEqual(r.status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.body, "First note")

    def test_manager_can_edit_and_delete_any_comment(self):
        c = self.new_comment(self.worker)
        self.login(self.admin)
        self.client.post(self.u("projectActionCommentEdit", self.a1, c.uuid), {"body": "Moderated"})
        c.refresh_from_db()
        self.assertEqual(c.body, "Moderated")
        self.client.post(self.u("projectActionCommentDelete", self.a1, c.uuid))
        self.assertFalse(ActionComment.objects.filter(pk=c.pk).exists())

    def test_author_deletes_own_comment(self):
        c = self.new_comment(self.worker)
        self.login(self.worker)
        r = self.client.post(self.u("projectActionCommentDelete", self.a1, c.uuid))
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        self.assertFalse(ActionComment.objects.filter(pk=c.pk).exists())

    def test_delete_get_is_405(self):
        c = self.new_comment(self.worker)
        self.login(self.worker)
        self.assertEqual(self.client.get(self.u("projectActionCommentDelete", self.a1, c.uuid)).status_code, 405)

    def test_comment_under_wrong_action_gets_404(self):
        c = self.new_comment(self.admin, action=self.a2)
        self.login(self.admin)
        self.assertEqual(self.client.get(self.u("projectActionCommentEdit", self.a1, c.uuid)).status_code, 404)
        self.assertEqual(self.client.post(self.u("projectActionCommentDelete", self.a1, c.uuid)).status_code, 404)
        self.assertTrue(ActionComment.objects.filter(pk=c.pk).exists())

    def test_archived_project_blocks_add_edit_delete(self):
        c = self.new_comment(self.worker)
        self.pa.archive()
        self.login(self.worker)
        self.client.post(self.u("projectActionCommentAdd", self.a1), {"body": "Late"})
        self.client.post(self.u("projectActionCommentEdit", self.a1, c.uuid), {"body": "Late edit"})
        self.client.post(self.u("projectActionCommentDelete", self.a1, c.uuid))
        self.assertEqual(ActionComment.objects.count(), 1)
        c.refresh_from_db()
        self.assertEqual(c.body, "First note")
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "First note")
        self.assertNotContains(r, "Add comment")
        self.assertNotContains(r, "Edit comment")

    def test_form_and_links_shown_to_the_right_people(self):
        self.new_comment(self.worker)
        self.login(self.worker)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "Add comment")
        self.assertContains(r, "Edit comment")
        self.login(self.mate)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, "Add comment")
        self.assertNotContains(r, "Edit comment")
        self.assertNotContains(r, "Delete comment")


class AttachmentTests(ExtrasBase):
    def add(self, user=None, upload=None, action=None):
        return services.add_attachment(action or self.a1, user or self.admin, upload or pdf_file())

    def post_file(self, upload, action=None):
        return self.client.post(self.u("projectActionAttachmentAdd", action or self.a1), {"file": upload})

    def test_member_uploads_each_allowed_type(self):
        self.login(self.mate)
        for upload in (pdf_file(), png_file(), jpg_file(), docx_file()):
            r = self.post_file(upload)
            self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        self.assertEqual(ActionAttachment.objects.count(), 4)

    def test_stored_under_org_path_with_random_name_and_safe_metadata(self):
        att = self.add(upload=pdf_file("../../evil.pdf"))
        prefix = "org_%s/actions/%s/" % (self.pa.organization_id, self.a1.uuid)
        self.assertTrue(att.file.name.startswith(prefix))
        self.assertNotIn("..", att.file.name)
        self.assertNotIn("evil", att.file.name)
        self.assertEqual(att.original_name, "evil.pdf")
        self.assertEqual(att.content_type, "application/pdf")
        self.assertEqual(att.uploaded_by_id, self.admin.pk)
        self.assertTrue(os.path.exists(self.stored(att)))

    def test_bad_files_are_rejected(self):
        self.login(self.admin)
        bad = [
            SimpleUploadedFile("big.pdf", b"%PDF-" + b"0" * (200 * 1024)),
            SimpleUploadedFile("fake.pdf", b"just some text"),
            SimpleUploadedFile("mismatch.jpg", b"\x89PNG\r\n\x1a\n" + b"0" * 10),
            SimpleUploadedFile("run.exe", b"MZ" + b"0" * 10),
            SimpleUploadedFile("page.html", b"<html></html>"),
            SimpleUploadedFile("empty.pdf", b""),
            SimpleUploadedFile("notzip.docx", b"PK not really a zip"),
            docx_file("noword.docx", with_word=False),
        ]
        for upload in bad:
            self.post_file(upload)
        self.assertEqual(ActionAttachment.objects.count(), 0)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_limit_of_20_files_per_action(self):
        for i in range(20):
            self.add(upload=pdf_file("f%d.pdf" % i))
        with self.assertRaises(ValidationError):
            self.add(upload=pdf_file("one_too_many.pdf"))
        self.assertEqual(ActionAttachment.objects.count(), 20)

    def test_download_sends_attachment_with_safe_headers(self):
        att = self.add(upload=pdf_file("report.pdf"))
        self.login(self.mate)
        r = self.client.get(self.u("projectActionAttachmentDownload", self.a1, att.uuid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4\nhello\n%%EOF")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("report.pdf", r["Content-Disposition"])
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", r["Cache-Control"])

    def test_detail_page_links_only_to_the_download_view(self):
        att = self.add()
        self.login(self.mate)
        r = self.client.get(self.detail_url(self.a1))
        self.assertContains(r, self.u("projectActionAttachmentDownload", self.a1, att.uuid))
        self.assertNotContains(r, att.file.name)

    def test_download_access_rules(self):
        att = self.add()
        url = self.u("projectActionAttachmentDownload", self.a1, att.uuid)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])
        self.login(self.beta_user)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        own = self.u("projectActionAttachmentDownload", self.a1, att.uuid, project=self.pc)
        self.assertEqual(self.client.get(own).status_code, 404)
        self.login(self.admin)
        wrong_action = self.u("projectActionAttachmentDownload", self.a2, att.uuid)
        self.assertEqual(self.client.get(wrong_action).status_code, 404)

    def test_download_of_missing_file_gets_404(self):
        att = self.add()
        os.remove(self.stored(att))
        self.login(self.admin)
        r = self.client.get(self.u("projectActionAttachmentDownload", self.a1, att.uuid))
        self.assertEqual(r.status_code, 404)

    def test_upload_access_rules(self):
        url = self.u("projectActionAttachmentAdd", self.a1)
        r = self.client.post(url, {"file": pdf_file()})
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=", r["Location"])
        self.login(self.mate)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.login(self.beta_user)
        self.assertEqual(self.post_file(pdf_file()).status_code, 404)
        self.login(self.outsider)
        self.assertEqual(self.post_file(pdf_file()).status_code, 404)
        self.assertEqual(ActionAttachment.objects.count(), 0)

    def test_uploader_deletes_own_and_file_is_removed(self):
        att = self.add(self.worker)
        path = self.stored(att)
        self.login(self.worker)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.u("projectActionAttachmentDelete", self.a1, att.uuid))
        self.assertRedirects(r, self.detail_url(self.a1), fetch_redirect_response=False)
        self.assertFalse(ActionAttachment.objects.filter(pk=att.pk).exists())
        self.assertFalse(os.path.exists(path))

    def test_other_member_cannot_delete_but_manager_can(self):
        att = self.add(self.worker)
        url = self.u("projectActionAttachmentDelete", self.a1, att.uuid)
        self.login(self.mate)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(ActionAttachment.objects.filter(pk=att.pk).exists())
        self.login(self.admin)
        self.client.post(url)
        self.assertFalse(ActionAttachment.objects.filter(pk=att.pk).exists())

    def test_archived_project_blocks_upload_and_delete_but_not_download(self):
        att = self.add()
        self.pa.archive()
        self.login(self.admin)
        self.post_file(pdf_file("late.pdf"))
        self.client.post(self.u("projectActionAttachmentDelete", self.a1, att.uuid))
        self.assertEqual(ActionAttachment.objects.count(), 1)
        r = self.client.get(self.u("projectActionAttachmentDownload", self.a1, att.uuid))
        self.assertEqual(r.status_code, 200)
        page = self.client.get(self.detail_url(self.a1))
        self.assertNotContains(page, "Upload")
        self.assertNotContains(page, "Delete attachment")

    def test_deleting_an_action_removes_its_files_after_commit(self):
        att = self.add(action=self.a2)
        path = self.stored(att)
        with self.captureOnCommitCallbacks(execute=True):
            services.delete_action(self.a2, self.admin)
        self.assertFalse(os.path.exists(path))

    def test_upload_form_visible_to_members(self):
        self.login(self.mate)
        self.assertContains(self.client.get(self.detail_url(self.a1)), "Upload")
