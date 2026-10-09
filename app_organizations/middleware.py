SESSION_KEY = "switched_org_id"


class CurrentOrganizationMiddleware:
    """
    Attach request.home_org and request.current_org.

    home_org is the org on the user's own employee profile.
    current_org is the same, except for a superuser who has switched
    into another org (its id is kept in the session). The session
    value is ignored for everyone else, and dropped if the org no
    longer exists. Anonymous users, or users without a profile, get None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.home_org = None
        request.current_org = None

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            from appEmp.models import empProfile
            from app_organizations.models import Organization

            profile = (
                empProfile.objects
                .select_related("organization")
                .filter(user=user)
                .first()
            )
            if profile is not None:
                request.home_org = profile.organization
                request.current_org = profile.organization

            if user.is_superuser:
                switched_id = request.session.get(SESSION_KEY)
                if switched_id:
                    try:
                        org = Organization.objects.filter(pk=switched_id).first()
                    except (TypeError, ValueError):
                        org = None
                    if org is None:
                        request.session.pop(SESSION_KEY, None)
                    else:
                        request.current_org = org

        return self.get_response(request)
