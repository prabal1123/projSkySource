CORE = "core"  # always on, never stored

# key -> label and the modules it needs. URL names are added in Phase 2.
MODULES = {
    "attendance":     {"label": "Attendance",           "requires": []},
    "holidays":       {"label": "Holidays",             "requires": []},
    "leave":          {"label": "Leave",                "requires": ["holidays"]},
    "exit_clearance": {"label": "Exit & clearance",     "requires": []},
    "documents":      {"label": "Documents",            "requires": []},
    "bcas":           {"label": "BCAS passes",          "requires": ["documents"]},
    "payroll":        {"label": "Payroll",              "requires": ["attendance"]},
    "projects":       {"label": "Projects",             "requires": [], "view_modules": ["app_projects"]},
    "bulk_import":    {"label": "Employee bulk import", "requires": []},
    "whatsapp":       {"label": "WhatsApp",             "requires": []},
}


def effective_modules(direct_keys):
    """Directly bought modules plus everything they require, transitively."""
    result = set()
    stack = list(direct_keys)
    while stack:
        key = stack.pop()
        if key in result or key not in MODULES:
            continue
        result.add(key)
        stack.extend(MODULES[key]["requires"])
    return result


def module_for_view(view_func):
    """Which module a view belongs to, or None if it is not gated yet."""
    path = getattr(view_func, "__module__", "") or ""
    for key, meta in MODULES.items():
        for prefix in meta.get("view_modules", []):
            if path == prefix or path.startswith(prefix + "."):
                return key
    return None