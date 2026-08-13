# from django.shortcuts import render, redirect
# from django.contrib import messages
# from django.contrib.auth.models import User
# from django.contrib.auth import authenticate, login, logout

# from .forms import LoginForm, registerEmp
# from .models import ActivityLog
# from appEmp.models import empProfile




# def home_view(request):
#     return render(request, "home.html")


# def login_view(request):
#     form = LoginForm(request.POST or None)
#     if request.method == "POST":
#         if form.is_valid():
#             username = form.cleaned_data["username"]
#             password = form.cleaned_data["password"]
#             user = authenticate(username=username, password=password)

#             if user is not None:
#                 login(request, user)
#                 ActivityLog.objects.create(
#                     user=user,
#                     action="User logged in",
#                     ip_address=request.META.get('REMOTE_ADDR'),
#                     user_agent=request.META.get('HTTP_USER_AGENT'),
#                 )
#                 return redirect("dashboard")
#             else:
#                 messages.error(request, "Invalid username or password.")
#     return render(request, "appAuth/login.html", {"form": form})


# def register_view(request):
#     form = registerEmp(request.POST or None)
#     if request.method == "POST":
#         if form.is_valid():
#             first_name = form.cleaned_data["first_name"]
#             last_name = form.cleaned_data["last_name"]
#             email = form.cleaned_data["email"]
#             username = form.cleaned_data["username"]
#             password = form.cleaned_data["password"]

#             if User.objects.filter(username=username).exists():
#                 messages.error(request, "That username is already taken.")
#                 return render(request, "appAuth/register.html", {"form": form})

#             user = User.objects.create_user(
#                 username=username,
#                 email=email,
#                 password=password,
#                 first_name=first_name,
#                 last_name=last_name,
#             )
#             emp_profile = empProfile.objects.filter(user=user).first()
#             return redirect("editProfile", uuid=emp_profile.uuid)
#     return render(request, "appAuth/register.html", {"form": form})


# def logout_view(request):
#     if request.user.is_authenticated:
#         ActivityLog.objects.create(
#             user=request.user,
#             action="User logged out",
#             ip_address=request.META.get('REMOTE_ADDR'),
#             user_agent=request.META.get('HTTP_USER_AGENT'),
#         )
#     logout(request)
#     return redirect("login")


# def dashboard_view(request):
#     if not request.user.is_authenticated:
#         return render(request, "appAuth/login.html", {"error": "You must be logged in to view the dashboard"})
#     # return redirect("dashboard")  # Redirect to the dashboard URL
#     return render(request, "dashboard.html", {"user": request.user})

# def logout_view(request):
#     log_entry = ActivityLog(user=request.user, action="User logged out", ip_address=request.META.get('REMOTE_ADDR'), user_agent=request.META.get('HTTP_USER_AGENT'))
#     log_entry.save()
#     logout(request)
#     return redirect("login")



from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout

from .forms import LoginForm, registerEmp
from .models import ActivityLog
from appEmp.models import empProfile


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


def login_view(request):
    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]

        user = authenticate(
            request=request,
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)

            ActivityLog.objects.create(
                user=user,
                action="User logged in",
                ip_address=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT") or "Unknown",
            )

            return redirect("dashboard")

        messages.error(request, "Invalid username or password.")

    return render(
        request,
        "appAuth/login.html",
        {"form": form},
    )


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
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]

        if User.objects.filter(username=username).exists():
            messages.error(request, "That username is already taken.")

            return render(
                request,
                "appAuth/register.html",
                {"form": form},
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

        emp_profile = empProfile.objects.filter(user=user).first()

        if emp_profile is None:
            messages.error(
                request,
                "Account created, but employee profile could not be found.",
            )
            return redirect("login")

        return redirect("editProfile", uuid=emp_profile.uuid)

    return render(
        request,
        "appAuth/register.html",
        {"form": form},
    )


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

