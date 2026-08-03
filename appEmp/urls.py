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
)

urlpatterns = [
    path("profile/<uuid:uuid>/", profileDetail_view, name="editProfile"),
    path('empProfile', empProfile_view, name='myProfile'),
    path('empList/', empList_view, name='employeeList'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('attendance/checkin-checkout/', checkin_checkout_view, name='checkinCheckout'),
    path('attendance/<uuid:uuid>/edit/', update_attendance_view, name='editAttendance'),
] 