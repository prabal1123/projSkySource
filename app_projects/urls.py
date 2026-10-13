from django.urls import path

from . import action_views, views

urlpatterns = [
    path("", views.project_list_view, name="projectList"),
    path("new/", views.project_create_view, name="projectCreate"),
    path("assign/", views.project_assign_view, name="projectAssign"),
    path("<uuid:uuid>/", views.project_detail_view, name="projectDetail"),
    path("<uuid:uuid>/edit/", views.project_edit_view, name="projectEdit"),
    path("<uuid:uuid>/archive/", views.project_archive_view, name="projectArchive"),
    path("<uuid:uuid>/unarchive/", views.project_unarchive_view, name="projectUnarchive"),
    path("my-actions/", action_views.my_actions_view, name="myActions"),
    path("<uuid:uuid>/actions/", action_views.action_list_view, name="projectActionList"),
    path("<uuid:uuid>/actions/new/", action_views.action_create_view, name="projectActionCreate"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/", action_views.action_detail_view, name="projectActionDetail"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/edit/", action_views.action_edit_view, name="projectActionEdit"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/status/", action_views.action_status_view, name="projectActionStatus"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/reassign/", action_views.action_reassign_view, name="projectActionReassign"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/delete/", action_views.action_delete_view, name="projectActionDelete"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/subtasks/new/", action_views.action_subtask_create_view, name="projectActionSubtaskCreate"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/comments/add/", action_views.action_comment_add_view, name="projectActionCommentAdd"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/comments/<uuid:comment_uuid>/edit/", action_views.action_comment_edit_view, name="projectActionCommentEdit"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/comments/<uuid:comment_uuid>/delete/", action_views.action_comment_delete_view, name="projectActionCommentDelete"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/attachments/add/", action_views.action_attachment_add_view, name="projectActionAttachmentAdd"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/attachments/<uuid:attachment_uuid>/download/", action_views.action_attachment_download_view, name="projectActionAttachmentDownload"),
    path("<uuid:uuid>/actions/<uuid:action_uuid>/attachments/<uuid:attachment_uuid>/delete/", action_views.action_attachment_delete_view, name="projectActionAttachmentDelete"),
]
