from django.urls import path

from . import views

urlpatterns = [
    path("", views.project_list_view, name="projectList"),
    path("new/", views.project_create_view, name="projectCreate"),
    path("assign/", views.project_assign_view, name="projectAssign"),
    path("<uuid:uuid>/", views.project_detail_view, name="projectDetail"),
    path("<uuid:uuid>/edit/", views.project_edit_view, name="projectEdit"),
    path("<uuid:uuid>/archive/", views.project_archive_view, name="projectArchive"),
    path("<uuid:uuid>/unarchive/", views.project_unarchive_view, name="projectUnarchive"),
]
