
"""
URL configuration for projSkySource project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

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
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
