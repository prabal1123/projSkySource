# from . import views
# from django.urls import path
# from django.contrib.auth import views as auth_views

# urlpatterns = [
#     path('', views.home_view, name='home'),
#     path('login/', views.login_view, name='login'),
#     path('dashboard/', views.dashboard_view, name='dashboard'),
#     path('logout/', views.logout_view, name='logout'),
#     path('register/', views.register_view, name='register'),
#     path('forgot-password/', auth_views.PasswordResetView.as_view(), name='password_reset'),
#     path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
#     path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
#     path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
# ]

from . import views
from django.urls import path
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    
    path('login/verify/', views.verify_otp_view, name='verify_otp'),

    # Email-based reset - wired but inactive until EMAIL_BACKEND is configured
    path('forgot-password/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # In-app change password (logged-in users) - active now
    path(
        'change-password/',
        auth_views.PasswordChangeView.as_view(
            template_name='appAuth/change_password.html',
            success_url='/app/change-password/done/',
        ),
        name='password_change',
    ),
    path(
        'change-password/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='appAuth/change_password_done.html'
        ),
        name='password_change_done',
    ),
]