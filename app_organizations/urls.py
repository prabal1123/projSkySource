from django.urls import path

from . import views

urlpatterns = [
    path("new/", views.create_org_view, name="create_organization"),
    path("switch/", views.switch_organization_view, name="switch_organization"),
]
