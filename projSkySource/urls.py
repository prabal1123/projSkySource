
"""
URL configuration for projSkySource project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path(
        "",
        RedirectView.as_view(url="/app/", permanent=False),
        name="root_redirect",
    ),

    path("admin/", admin.site.urls),
    path("app/", include("appAuth.urls")),
    path("emp/", include("appEmp.urls")),
]