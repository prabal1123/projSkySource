from .models import empProfile, ADMIN_ROLES


def user_role(request):
    if request.user.is_authenticated:
        profile = empProfile.objects.filter(user=request.user).first()
        if profile:
            return {"is_admin_role": profile.role in ADMIN_ROLES}
    return {"is_admin_role": False}