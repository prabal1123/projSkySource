from .entitlements import modules_for_request


def module_flags(request):
    """Templates can use: {% if 'projects' in org_modules %}"""
    return {"org_modules": modules_for_request(request)}