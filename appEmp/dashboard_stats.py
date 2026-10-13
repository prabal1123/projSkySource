from django.db.models import Count, Q

from app_projects.models import Action, Project
from appEmp.models import empProfile


def project_overview(org, today):
    people = {
        r["project"]: r["n"]
        for r in empProfile.objects.filter(organization=org, is_active=True)
        .values("project")
        .order_by()
        .annotate(n=Count("id"))
    }
    work = {
        r["project"]: r
        for r in Action.objects.filter(
            organization=org, status__in=Action.OPEN_STATUSES
        )
        .values("project")
        .order_by()
        .annotate(
            open=Count("id"),
            overdue=Count("id", filter=Q(due_date__lt=today)),
        )
    }
    rows = []
    for p in (
        Project.objects.filter(organization=org)
        .exclude(status=Project.STATUS_ARCHIVED)
        .order_by("name")
    ):
        rows.append({
            "name": p.name,
            "uuid": p.uuid,
            "people": people.get(p.pk, 0),
            "open": work.get(p.pk, {}).get("open", 0),
            "overdue": work.get(p.pk, {}).get("overdue", 0),
        })
    return {"rows": rows, "unassigned": people.get(None, 0)}
