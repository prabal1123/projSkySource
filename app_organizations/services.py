from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from .models import Organization, OrganizationMember
from .seed import (
    copy_import_config,
    ensure_org_admin_group,
    seed_org_defaults,
)


def create_organization(
    *, name, owner_email, owner_first_name, owner_last_name="", created_by
):
    """
    Create an organization with its first owner, all or nothing.

    Raises ValueError with a message safe to show the person using the form.
    Returns (organization, owner_user).
    """
    User = get_user_model()

    name = (name or "").strip()
    owner_email = (owner_email or "").strip()
    owner_first_name = (owner_first_name or "").strip()
    owner_last_name = (owner_last_name or "").strip()

    if not name:
        raise ValueError("Organization name is required.")
    if not owner_first_name:
        raise ValueError("Owner first name is required.")
    if not owner_email:
        raise ValueError("Owner email is required.")
    try:
        validate_email(owner_email)
    except ValidationError:
        raise ValueError("Enter a valid owner email address.")

    if Organization.objects.filter(name__iexact=name).exists():
        raise ValueError("An organization with this name already exists.")
    if User.objects.filter(email__iexact=owner_email).exists():
        raise ValueError("An account with this email already exists.")

    with transaction.atomic():
        org = Organization.objects.create(name=name, created_by=created_by)

        # Masters first, so the owner gets the default shift from the signal.
        seed_org_defaults(org)
        copy_import_config(org)
        group = ensure_org_admin_group()

        owner = User(
            username=owner_email,
            email=owner_email,
            first_name=owner_first_name,
            last_name=owner_last_name,
        )
        owner.set_unusable_password()
        owner._organization = org
        owner.save()

        membership = OrganizationMember.objects.get(user=owner)
        if membership.organization_id != org.id:
            raise RuntimeError("Owner was attached to the wrong organization.")
        membership.role = "owner"
        membership.save(update_fields=["role"])

        owner.groups.add(group)

    return org, owner
