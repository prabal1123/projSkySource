# Phase 4 deployment notes

## Every deploy that includes projects

1. Back up the database.
2. python manage.py migrate
3. python manage.py sync_project_permissions

Step 3 adds view_all_projects and manage_projects to the ORG_ADMIN and
HR_ADMIN groups. Without it, existing admins in those groups cannot see
or manage projects. Owners, admins and managers by organization role are
not affected, because project access also passes by role. The command only
adds permissions and is safe to run again.

New organizations get the permissions automatically through
ensure_org_admin_group.

## Migrations so far

- app_projects 0001: Project table
- appEmp 0071: empProfile.project (nullable)
- app_projects 0002: project permissions (no table change)
