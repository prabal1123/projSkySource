from django.shortcuts import render

from .entitlements import modules_for_request
from .modules import MODULES, module_for_view


class ModuleAccessMiddleware:
    """Block views whose module the current organization has not bought."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        key = module_for_view(view_func)
        if key is None:
            return None  # not gated

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None  # the view's own login handling applies
        if user.is_superuser:
            return None

        if key in modules_for_request(request):
            return None

        return render(
            request,
            "errors/module_not_available.html",
            {"module_label": MODULES[key]["label"]},
            status=403,
        )