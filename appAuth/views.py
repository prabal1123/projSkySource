


import random
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings

from .forms import LoginForm, registerEmp, RequestOTPForm, VerifyOTPForm
from .models import ActivityLog
from appEmp.models import empProfile, EmailOTP
from .utils import send_azure_otp


def get_client_ip(request):
    """
    Get the real client IP when Django is running behind Nginx.
    """

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return (
        request.META.get("HTTP_X_REAL_IP")
        or request.META.get("REMOTE_ADDR")
        or "0.0.0.0"
    )


def home_view(request):
    return render(request, "home.html")


# def login_view(request):
#     form = LoginForm(request.POST or None)

#     if request.method == "POST" and form.is_valid():
#         username = form.cleaned_data["username"]
#         password = form.cleaned_data["password"]

#         user = authenticate(
#             request=request,
#             username=username,
#             password=password,
#         )

#         if user is not None:
#             login(request, user)

#             ActivityLog.objects.create(
#                 user=user,
#                 action="User logged in",
#                 ip_address=get_client_ip(request),
#                 user_agent=request.META.get("HTTP_USER_AGENT") or "Unknown",
#             )

#             return redirect("dashboard")

#         messages.error(request, "Invalid username or password.")

#     return render(
#         request,
#         "appAuth/login.html",
#         {"form": form},
#     )

def login_view(request):
    """
    Step 1: employee enters their email. If an empProfile exists for that
    email, an OTP is generated and emailed. Unknown emails are rejected —
    only admin-provisioned accounts (via register_view) can log in.
    """
    form = RequestOTPForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]

        user = User.objects.filter(email__iexact=email, empprofile__isnull=False).first()

        if not user:
            messages.error(request, "No employee account found for this email. Contact HR/Admin.")
            return render(request, "appAuth/login.html", {"form": form})

        otp = f"{random.randint(100000, 999999)}"
        EmailOTP.objects.create(email=email, code=otp)

        email_sent = send_azure_otp(email, otp)

        if not email_sent:
            messages.error(request, "Failed to send code. Please try again shortly.")
            return render(request, "appAuth/login.html", {"form": form})

        request.session["pending_login_email"] = email
        return redirect("verify_otp")

    return render(request, "appAuth/login.html", {"form": form})


def verify_otp_view(request):
    """
    Step 2: employee enters the OTP they received by email.
    """
    email = request.session.get("pending_login_email")
    if not email:
        messages.error(request, "Please enter your email first.")
        return redirect("login")

    form = VerifyOTPForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["otp"]

        otp_obj = (
            EmailOTP.objects.filter(email__iexact=email, code=code)
            .order_by("-created_at")
            .first()
        )

        if not otp_obj or not otp_obj.is_valid():
            messages.error(request, "Invalid or expired code.")
            return render(request, "appAuth/verify_otp.html", {"form": form, "email": email})

        user = User.objects.filter(email__iexact=email, empprofile__isnull=False).first()
        if not user:
            messages.error(request, "No employee account found for this email.")
            return redirect("login")

        otp_obj.used = True
        otp_obj.save()

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        ActivityLog.objects.create(
            user=user,
            action="User logged in via OTP",
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT") or "Unknown",
        )

        del request.session["pending_login_email"]
        return redirect("dashboard")

    return render(request, "appAuth/verify_otp.html", {"form": form, "email": email})


# def register_view(request):
#     requester_profile = empProfile.objects.filter(user=request.user).first()

#     if not requester_profile or not (
#         request.user.is_superuser
#         or request.user.has_perm("appEmp.manage_employees")
#     ):
#         messages.error(request, "You don't have permission to add employees.")
#         return redirect("dashboard")
#     form = registerEmp(request.POST or None)

#     if request.method == "POST" and form.is_valid():
#         first_name = form.cleaned_data["first_name"]
#         last_name = form.cleaned_data["last_name"]
#         email = form.cleaned_data["email"]
#         username = form.cleaned_data["username"]
#         password = form.cleaned_data["password"]

#         if User.objects.filter(username=username).exists():
#             messages.error(request, "That username is already taken.")

#             return render(
#                 request,
#                 "appAuth/register.html",
#                 {"form": form},
#             )

#         user = User.objects.create_user(
#             username=username,
#             email=email,
#             password=password,
#             first_name=first_name,
#             last_name=last_name,
#         )

#         emp_profile = empProfile.objects.filter(user=user).first()

#         if emp_profile is None:
#             messages.error(
#                 request,
#                 "Account created, but employee profile could not be found.",
#             )
#             return redirect("login")

#         return redirect("editProfile", uuid=emp_profile.uuid)

#     return render(
#         request,
#         "appAuth/register.html",
#         {"form": form},
#     )

def register_view(request):
    requester_profile = empProfile.objects.filter(user=request.user).first()

    if not requester_profile or not (
        request.user.is_superuser
        or request.user.has_perm("appEmp.manage_employees")
    ):
        messages.error(request, "You don't have permission to add employees.")
        return redirect("dashboard")

    form = registerEmp(request.POST or None)

    if request.method == "POST" and form.is_valid():
        first_name = form.cleaned_data["first_name"]
        last_name = form.cleaned_data["last_name"]
        email = form.cleaned_data["email"]

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email already exists.")
            return render(request, "appAuth/register.html", {"form": form})

        user = User.objects.create(
            username=email,  # email doubles as username since login is email/OTP-based
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()

        emp_profile = empProfile.objects.filter(user=user).first()

        if emp_profile is None:
            messages.error(
                request,
                "Account created, but employee profile could not be found.",
            )
            return redirect("login")

        return redirect("editProfile", uuid=emp_profile.uuid)

    return render(request, "appAuth/register.html", {"form": form})


def logout_view(request):
    if request.user.is_authenticated:
        ActivityLog.objects.create(
            user=request.user,
            action="User logged out",
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT") or "Unknown",
        )

    logout(request)
    return redirect("login")


def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect("login")

    return render(
        request,
        "dashboard.html",
        {"user": request.user},
    )

