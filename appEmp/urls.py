# from . import views
# from django.urls import path
# from .views import (empProfile_view
# , empList_view
# , profileDetail_view
# )

# urlpatterns = [
#     path("profile/<uuid:uuid>/", profileDetail_view, name="editProfile"),
#     path('empProfile', empProfile_view, name='myProfile'),
#     path('empList/', empList_view, name='employeeList'),
#     ]

from . import views
from django.urls import path
from .views import (
    empProfile_view,
    empList_view,
    profileDetail_view,
    dashboard_view,
    checkin_checkout_view,
    update_attendance_view,
    salary_update_view,
    salary_slip_self_view,
    salary_slip_admin_view,
)

urlpatterns = [
    path("profile/<uuid:uuid>/", profileDetail_view, name="editProfile"),
    path('empProfile', empProfile_view, name='myProfile'),
    path('empList/', empList_view, name='employeeList'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('attendance/checkin-checkout/', checkin_checkout_view, name='checkinCheckout'),
    path('attendance/<uuid:uuid>/edit/', update_attendance_view, name='editAttendance'),
    # ── Add to appEmp/urls.py, inside urlpatterns ────────────────────────────



    path('salary/save/<uuid:uuid>/', views.salary_update_view, name='salaryUpdate'),
    path('salary/slip/<int:year>/<int:month>/', views.salary_slip_self_view, name='salarySlipSelf'),
    path('salary/<uuid:uuid>/slip/<int:year>/<int:month>/', views.salary_slip_admin_view, name='salarySlipAdmin'),
] 