from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import CreateOrganizationForm
from .middleware import SESSION_KEY
from .models import Organization
from .services import create_organization


@login_required
def create_org_view(request):
    # Server-side check: only superusers may create organizations.
    if not request.user.is_superuser:
        raise PermissionDenied

    created = None
    form = CreateOrganizationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            org, owner = create_organization(
                name=form.cleaned_data["org_name"],
                owner_email=form.cleaned_data["owner_email"],
                owner_first_name=form.cleaned_data["owner_first_name"],
                owner_last_name=form.cleaned_data["owner_last_name"],
                created_by=request.user,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            created = {"org": org, "owner": owner}
            form = CreateOrganizationForm()

    return render(
        request,
        "app_organizations/create_org.html",
        {"form": form, "created": created},
    )


@login_required
@require_POST
def switch_organization_view(request):
    # Server-side check: only superusers may switch organizations.
    if not request.user.is_superuser:
        raise PermissionDenied

    raw_id = request.POST.get("org_id", "").strip()
    home_org = getattr(request, "home_org", None)

    org = None
    if raw_id:
        org = Organization.objects.filter(pk=raw_id).first() if raw_id.isdigit() else None
        if org is None:
            messages.error(request, "That organization does not exist.")
            return redirect("dashboard")

    # A preview staged in one org must never be confirmed in another.
    request.session.pop("employee_import_rows", None)
    request.session.pop("holiday_import_rows", None)

    if org is None or (home_org is not None and org.pk == home_org.pk):
        request.session.pop(SESSION_KEY, None)
        messages.info(request, "You are back in your own organization.")
    else:
        request.session[SESSION_KEY] = org.pk
        messages.success(request, f"You are now working inside {org.name}.")

    return redirect("dashboard")
