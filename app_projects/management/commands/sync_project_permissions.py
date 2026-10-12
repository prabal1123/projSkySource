from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from app_organizations.seed import ORG_ADMIN_GROUP, ORG_ADMIN_PROJECT_PERMISSIONS

TARGET_GROUPS = (ORG_ADMIN_GROUP, "HR_ADMIN")


class Command(BaseCommand):
    help = (
        "Add the project permissions to the ORG_ADMIN and HR_ADMIN groups. "
        "Only adds, never removes, and is safe to run again."
    )

    def handle(self, *args, **options):
        perms = list(
            Permission.objects.filter(
                content_type__app_label="app_projects",
                codename__in=ORG_ADMIN_PROJECT_PERMISSIONS,
            )
        )
        if len(perms) != len(ORG_ADMIN_PROJECT_PERMISSIONS):
            raise CommandError("Project permissions are missing. Run migrate first.")

        perm_ids = [p.pk for p in perms]
        for name in TARGET_GROUPS:
            group = Group.objects.filter(name=name).first()
            if group is None:
                self.stdout.write(name + ": group not found, skipped")
                continue
            before = group.permissions.filter(pk__in=perm_ids).count()
            group.permissions.add(*perms)
            self.stdout.write(
                name + ": " + str(len(perms) - before) + " added, "
                + str(before) + " already present"
            )
