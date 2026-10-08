


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
from .utils import send_azure_otp, send_demo_notification
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from appEmp.models import empProfile, EmailOTP, WhatsAppOTP
from appEmp.whatsapp_utils import send_whatsapp_otp
from .forms import LoginForm, registerEmp, RequestOTPForm, VerifyOTPForm, RequestWhatsAppOTPForm
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


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


# def home_view(request):
#     return render(request, "home.html")

# def home_view(request):
#     if request.user.is_authenticated:
#         return redirect('dashboard')
#     return render(request, "home.html")

def home_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, "home.html", {
        "lite_signup_url": getattr(settings, "LITE_SIGNUP_URL", "#book-demo"),
        "lite_login_url": getattr(settings, "LITE_LOGIN_URL", "#"),
    })


def demo_request(request):
    from django.contrib import messages
    from .models import DemoRequest
    if request.method == "POST" and not request.POST.get("website"):
        d = {k: request.POST.get(k, "").strip() for k in ("name", "company", "team_size", "phone", "email", "message")}
        digits = "".join(c for c in d["phone"] if c.isdigit())
        try:
            validate_email(d["email"])
            email_ok = True
        except ValidationError:
            email_ok = False

        required = ("name", "company", "team_size", "phone")
        if all(d[k] for k in required) and email_ok and 10 <= len(digits) <= 13 and len(d["message"]) <= 500:
            obj = DemoRequest.objects.create(**d)
            send_demo_notification(obj)
            messages.success(request, "Thanks! We'll call you to schedule your demo.")
        else:
            messages.error(request, "Please fill every field with a valid phone number and email.")
    return redirect("/app/#book-demo")

def contact_us(request):
    from .models import ContactQuery
    if request.method == "POST" and not request.POST.get("website"):
        d = {k: request.POST.get(k, "").strip() for k in ("name", "company", "email", "phone", "message")}
        digits = "".join(c for c in d["phone"] if c.isdigit())
        try:
            validate_email(d["email"])
            email_ok = True
        except ValidationError:
            email_ok = False

        if d["name"] and d["message"] and email_ok and len(d["message"]) <= 500 and (not digits or 10 <= len(digits) <= 13):
            obj = ContactQuery.objects.create(**d)
            send_contact_notification(obj)
            messages.success(request, "Thanks! We've received your message and will get back to you shortly.", extra_tags="contact")
        else:
            messages.error(request, "Please enter your name, a valid email and a message (max 500 characters).", extra_tags="contact")
    return redirect("/app/#contact")

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
            messages.error(request, "This email is not registered. Contact HR/Admin to get access.")
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



# def login_view(request):
#     """
#     Step 1: employee enters their WhatsApp number. If an empProfile exists
#     with that number, an OTP is generated and sent via WhatsApp.
#     """
#     form = RequestWhatsAppOTPForm(request.POST or None)

#     if request.method == "POST" and form.is_valid():
#         phone_number = form.cleaned_data["phone_number"].strip()

#         profile = empProfile.objects.filter(phone_number=phone_number).first()

#         if not profile:
#             messages.error(request, "This number is not registered. Contact HR/Admin to get access.")
#             return render(request, "appAuth/login.html", {"form": form})

#         otp = f"{random.randint(100000, 999999)}"
#         WhatsAppOTP.objects.create(phone_number=phone_number, code=otp)

#         status_code, response_data = send_whatsapp_otp(f"91{phone_number}", otp)

#         if status_code != 200:
#             messages.error(request, "Failed to send code. Please try again shortly.")
#             return render(request, "appAuth/login.html", {"form": form})

#         request.session["pending_login_phone"] = phone_number
#         return redirect("verify_otp")

#     return render(request, "appAuth/login.html", {"form": form})


# def verify_otp_view(request):
#     """
#     Step 2: employee enters the OTP they received on WhatsApp.
#     """
#     phone_number = request.session.get("pending_login_phone")
#     if not phone_number:
#         messages.error(request, "Please enter your WhatsApp number first.")
#         return redirect("login")

#     form = VerifyOTPForm(request.POST or None)

#     if request.method == "POST" and form.is_valid():
#         code = form.cleaned_data["otp"]

#         otp_obj = (
#             WhatsAppOTP.objects.filter(phone_number=phone_number, code=code)
#             .order_by("-created_at")
#             .first()
#         )

#         if not otp_obj or not otp_obj.is_valid():
#             messages.error(request, "Invalid or expired code.")
#             return render(request, "appAuth/verify_otp.html", {"form": form, "phone_number": phone_number})

#         profile = empProfile.objects.filter(phone_number=phone_number).first()
#         if not profile:
#             messages.error(request, "No employee account found for this number.")
#             return redirect("login")

#         otp_obj.used = True
#         otp_obj.save()

#         login(request, profile.user, backend="django.contrib.auth.backends.ModelBackend")

#         ActivityLog.objects.create(
#             user=profile.user,
#             action="User logged in via WhatsApp OTP",
#             ip_address=get_client_ip(request),
#             user_agent=request.META.get("HTTP_USER_AGENT") or "Unknown",
#         )

#         del request.session["pending_login_phone"]
#         return redirect("dashboard")

#     return render(request, "appAuth/verify_otp.html", {"form": form, "phone_number": phone_number})
