# appEmp split — plan & handoff (projSkySource / NumaHr Pro)

## 0. How to use this file
- New chat: give the repo URL + "Do Phase N of docs/APP_SPLIT_PLAN.md". Claude clones, reads this file, checks `git log` shows Phases 0..N-1 merged, then does ONLY Phase N.
- Workflow: discuss first, then implement. One branch per phase (`refactor/phase-N-<app>`), merged to main only after the Definition of Done (§5) passes.
- At the end of each phase Claude gives a status line for §8; paste it into this file and push.

## 0b. Working rules (locked)
**Delivery**
- Each phase is delivered as ONE patch file (`phaseN_<app>.patch`, made with `git diff --staged -M` so file moves show as renames).
- Apply on a fresh branch off main:
  `git checkout -b refactor/phase-N-<app>` → `git apply --check phaseN_<app>.patch` → `git apply --index phaseN_<app>.patch`
- Claude gives the commands and the test steps in chat. Code is not pasted in chat for these phases because they are mostly file moves.

**Tests and token budget**
- Claude does NOT run the Django test suite (or `migrate`, or `manage.py test`) in its sandbox. It needs Postgres, returns nothing useful, and burns the token budget.
- The user runs the tests locally and pastes the summary line (`Ran N tests ... OK` or `FAILED (failures=..)` plus the names of failing tests).
- Allowed in the sandbox, cheap checks only: `python -m compileall`, grep for leftover imports of moved names, comparing the URL-name list by reading `urls.py`.
- Migration files: Claude may run `makemigrations` ONCE per phase using a throwaway SQLite settings file, only to generate the CreateModel operations, then wraps them in `SeparateDatabaseAndState`. If that attempt fails, Claude writes the migration by hand. It does not retry in loops.
- Claude never dumps whole large files into the context: use targeted `grep -n` and `sed -n 'a,bp'` ranges, and scripted moves (`git mv`, `sed`) instead of retyping code.
- No scope creep: only what the phase lists. Anything extra is mentioned and left for the user to approve.

## 1. Locked decisions
1. Leave + attendance + holidays live together in `app_attendance`.
2. Option A: tables KEEP their current names. Moves are state-only (`SeparateDatabaseAndState`) with `Meta.db_table` set to the exact existing name. No SQL runs on RDS.
3. URLs: no namespaces today; URL names are global; everything mounts at `/emp/`. Each new app's `urls.py` is included under the same `emp/` prefix with identical paths and names. So `{% url %}` calls and `app_organizations/modules.py` do not change.
4. No re-export shims. When a model moves, every import of it is updated (`appEmp.models` never re-exports from new apps).
5. App names follow `app_<domain>` (like `app_organizations`, `app_projects`).
6. Custom permissions are all declared on `empProfile.Meta.permissions` (stays in appEmp), so `appEmp.review_leave` etc. do not change.
7. `fields.py`, `blind_index.py`, `signals.py`, `templatetags/` stay in core (app_projects migrations already import `appEmp.fields`).

## 2. Current state (main @ 21cc279)
- appEmp ≈ 21k lines: models.py 3,232 (33 models), views.py 6,701, forms.py 1,995, admin.py 690, 15 payroll/encryption test files.
- DB: Postgres (RDS); test DB `test_projskysource`. Deployment: EC2 + Nginx + Gunicorn.
- Imports from other apps into appEmp: appAuth (empProfile, EmailOTP, WhatsAppOTP, send_whatsapp_otp), app_organizations (middleware, entitlements, seed.py, tests), app_projects (access, services, action_views, context_processors, `OrgColumnMixin` from appEmp.admin, tests import Salary/Attendance/LeaveBalance/LeaveRequest/LeaveTypeMaster, `appEmp.views._filtered_emp_queryset`, `appEmp.dashboard_stats`).
- Core imports "upward" in aggregator spots: `dashboard_view`, `context_processors.user_role` (ClearanceApproval), profile pages (`_profile_payroll_estimate`).

## 3. Target layout
```
            app_payroll
            /         \
   app_attendance   app_exit     app_bcas   app_whatsapp
            \          |           /           /
                  appEmp (core)  ---------------
```
Rule: a higher app may import a lower one; core never imports upward at module level. Aggregator spots import lazily inside the function.

| App | Models | Code that moves with it |
|---|---|---|
| appEmp (core, stays) | empProfile, EmployeeImportFieldConfig, DesignationMaster, ShiftMaster, WorkSchedule*, DocumentTypeMaster, empDocument, EmailOTP, WhatsAppOTP | employee list/profile/verification/dashboard/documents/bulk-import views, fields, blind_index, signals, context_processors, dashboard_stats |
| app_bcas | Airport, BCASPass | 2 forms, 5 view fns |
| app_whatsapp | WhatsAppTicket | whatsapp_router, whatsapp_utils, webhook view |
| app_attendance | Attendance, AttendanceException, LeaveTypeMaster, LeaveBalance, LeaveRequest, Holiday, OptionalHolidayRequest | attendance/leave/holiday/work-schedule views + forms |
| app_exit | ClearanceRequest, ClearanceApproval, EmployeeExitRequest | services.py, exit/clearance views + forms |
| app_payroll | Salary, WageRegisterEntry, PayrollRecord, StatutoryRule, ProfessionalTaxSlab, IncomeTaxSlab, PayrollAuditLog, EmployeeStatutoryProfile, FinalSettlement, FinalSettlementItem, FinalSettlementLog | payroll_service, payroll_views, ctc, tds, statutory, professional_tax, ecr, esi_return, bank_file, payslip_pdf, settlement_pdf, salary/statutory/wage-register views + forms, 14 test files |

*WorkSchedule/ShiftMaster stay in core because `empProfile` has FKs to them (moving would make a cycle). Their VIEWS (work_schedule_*) move to app_attendance.
Why FinalSettlement is in payroll: payroll_views + modules.py treat it as payroll; payroll_service imports EmployeeExitRequest; exit's services.py never touches settlement.

## 4. The move recipe (used in every phase)
R1. Record exact table names: `python manage.py shell -c "from appEmp.models import X; print(X._meta.db_table)"` (note: capital E, e.g. `appEmp_attendance`).
R2. `python manage.py startapp app_x`; add to INSTALLED_APPS after appEmp; `apps.py` name `app_x`.
R3. Cut model classes (parents before children) into `app_x/models.py`. Add/merge `class Meta: db_table = "<exact name from R1>"`, keep all other Meta (ordering, permissions, constraints, indexes). FKs to moved siblings use `"app_x.Model"`; FKs to core use `"appEmp.empProfile"`.
R4. `app_x/migrations/0001_initial.py`: generate the CreateModel ops (see §0b: one `makemigrations` attempt with a throwaway SQLite settings file, else by hand), then wrap them in `SeparateDatabaseAndState(state_operations=[...])` with NO database_operations. Dependency: latest appEmp migration.
R5. appEmp migration `NNNN_move_<x>_to_app_x.py`: depends on previous appEmp + `("app_x","0001_initial")`. `SeparateDatabaseAndState(state_operations=[DeleteModel(...)])`, children first, NO database ops. If a model that STAYS in appEmp has an FK to a moved model, add an `AlterField` to repoint it inside the same `state_operations` (otherwise Django would drop/recreate the FK constraint).
R6. In app_x 0001 add a `RunPython` that relabels ContentType rows (`app_label` appEmp → app_x for each moved model; skip if target exists; reverse swaps back). Keeps admin history and default model permissions. Runs before post_migrate creates new rows.
R7. Fix imports everywhere: `grep -rn "<ModelName>" --include=*.py .` (appEmp views/forms/admin/services/context_processors/management, appAuth, app_organizations incl. seed.py and tests, app_projects incl. tests).
R8. Move forms, service modules, views, admin classes, tests. New `app_x/urls.py`; include in `projSkySource/urls.py` under `"emp/"`. Paths and `name=` identical.
R9. Templates: `git mv templates/appEmp/<f>.html templates/app_x/<f>.html`, update `render(...)` paths, grep `{% include %}` / `{% extends %}`. Separate commit so it can be reverted alone.
R10. Prove the DB is untouched (user, locally): `sqlmigrate app_x 0001` and the appEmp move migration print no SQL; `makemigrations --check --dry-run` is clean.

## 5. Definition of Done (every phase)
1. (User, locally) `python manage.py check` is OK and `python manage.py makemigrations --check --dry-run` says no changes.
2. (User, locally) `python manage.py test`: same passing count as `docs/split/baseline.txt`; tests moved, none lost. Paste the summary line back.
3. (Claude, by reading `urls.py`) URL names list identical to `docs/split/url_names.txt`; `app_organizations` module-coverage tests are part of item 2.
4. (User, locally) `sqlmigrate` for the move prints no SQL. `migrate` works on a fresh DB and on a copy of a data DB.
5. (Claude, grep) zero imports of moved names from `appEmp.models|views|forms`.
6. Phase smoke list clicked through manually by the user.
7. Deploy: RDS snapshot → deploy → `migrate` → restart gunicorn → smoke. Rollback: reverse-migrate (state-only), then redeploy previous commit.

## 6. Phases

### Phase 0 — Baseline & shared helpers (no behaviour change)
- User runs the full suite locally and pastes the summary; Claude writes it plus any pre-existing failures into `docs/split/baseline.txt`. Claude does not run the suite itself.
- Dump all URL names by reading the `urls.py` files to `docs/split/url_names.txt`; record latest appEmp migration number and `_meta.db_table` of every model that will move to `docs/split/tables.txt`.
- Extract cross-domain helpers from `views.py` into `appEmp/access.py`: `user_has_permission`, `user_has_hr_access`, `can_review_leave`, `can_review_attendance_exception`, `_filtered_emp_queryset` (+ any other helper used by more than one domain; find by grep). `views.py` imports them back. Reason: new apps must not import `appEmp.views` (circular). Update `app_projects` imports of `_filtered_emp_queryset`.
- Move `OrgColumnMixin` from `appEmp/admin.py` to `appEmp/admin_mixins.py`; update `app_projects/admin.py`.
- Done when: DoD 1–3 pass and diff contains no model/migration change.

### Phase 1 — app_bcas (pilot, smallest, nothing depends on it)
- Models: Airport, BCASPass. Forms: BCASPassForm, BCASPassStatusForm.
- Views: `_bcas_pass_status_counts`, `bcas_pass_dashboard_view`, `bcas_pass_issue_view`, `bcas_pass_status_update_view`, `bcas_pass_export_csv_view`.
- URL names (keep): bcasPassDashboard, bcasPassIssue, bcasPassStatusUpdate, bcasPassExport. Template: `bcas_pass_dashboard.html` (grep for others). Admin: Airport, BCASPass.
- Watch: BCAS counts in dashboard/context_processors; `seed.py`.
- Smoke: dashboard, issue pass, change status, export CSV.

### Phase 2 — app_whatsapp
- Model: WhatsAppTicket. Files: `whatsapp_router.py`, `whatsapp_utils.py`. View: `whatsapp_webhook` (views.py ≈ 6297–6383).
- WhatsAppOTP stays in core (login). `appAuth/views.py` imports `send_whatsapp_otp` from the new app.
- MUST NOT change the path `/emp/whatsapp/webhook/` (registered in the WhatsApp Cloud API dashboard).
- Update: views.py router imports (≈ lines 100–116), `app_organizations/test_whatsapp_gate.py` (imports `appEmp.views` + router), `appEmp/test_phase2_encryption.py` (`find_employee_by_phone`).
- Smoke: webhook verification request + a sample POST payload; ticket created; OTP login still sends.

### Phase 3 — app_attendance (attendance + leave + holidays)
- Models (7): Attendance, AttendanceException, LeaveTypeMaster, LeaveBalance, LeaveRequest, Holiday, OptionalHolidayRequest.
- Forms: AttendanceUpdateForm, AttendanceExceptionForm, AttendanceExceptionReviewForm, LeaveRequestForm, LeaveRequestReviewForm, LeaveBalanceForm, HolidayForm, HolidayBulkUploadForm, WorkScheduleForm, OptionalHolidayRequestForm.
- Views: checkin_checkout, update_attendance, attendance_location, attendance_calendar_self/admin, raise_attendance_exception, pending/review_attendance_exception(s), apply_leave, my/pending/all_leave_requests, review_leave_request, leave_balance_list/edit, holiday_list/create/edit/calendar/year/bulk_upload, optional_holiday_apply, pending/review_optional_holiday_request(s), work_schedule_list/create/edit. Helpers: `_get_attendance_date`, `_is_employee_late`, `_get_employee_day_context`, `_build_attendance_calendar`, `_build_holiday_calendar`, `_build_holiday_year`, `_mandatory_holiday_count`.
- Admin: Attendance, AttendanceException, LeaveTypeMaster, LeaveBalance, LeaveRequest, Holiday (Shift/WorkSchedule admin stays).
- Watch: `dashboard_view`, profile pages and `context_processors` read attendance/leave → lazy imports; `app_organizations/seed.py` (≈ line 67) imports models from appEmp; `app_projects` tests (`test_attendance_filters`, `test_leave_filters`); `app_projects` filters/dashboard code (grep); `_mandatory_holiday_count` is used by payroll code (payroll imports from here, correct direction).
- Smoke: check-in/out, calendar (self + admin), exception raise/review, apply + approve leave, balances, holiday add/bulk upload/calendar, optional holiday apply/review, work schedules.

### Phase 4 — app_exit
- Models: ClearanceRequest, ClearanceApproval, EmployeeExitRequest. `services.py` (all 8 functions) → `app_exit/services.py`.
- Forms: ResignationForm, ResignationReviewForm, ClearanceApprovalDecisionForm, TerminationForm.
- Views: submit_resignation, my_resignations, pending_resignations, review_resignation, manager_clearance_queue/review, finance_clearance_queue/review, ready_for_finalization, finalize_employee_exit, initiate_termination, all_exit_requests. Templates incl. `exit_clearance_dashboard.html`.
- R5 special case: `FinalSettlement` (still in appEmp until Phase 5) has an FK to EmployeeExitRequest → repoint in state_operations.
- Watch: `context_processors.user_role` imports ClearanceApproval (lazy import); `dashboard_view` exit/clearance blocks (≈ lines 1035–1085); permission strings stay `appEmp.*`; `payroll_service` imports EmployeeExitRequest (update import now).
- Smoke: resign → HR review → manager + finance clearance → ready-for-finalization → finalize; initiate termination; all-requests list.

### Phase 5 — app_payroll (largest; two sub-phases, can be separate chats)
- 5a — models + migrations + admin: the 11 models, `statutory.py` (models.py imports `get_rule`) and any helper models import (grep at the time), admin classes (Salary, WageRegisterEntry, StatutoryRule, PayrollAuditLog, FinalSettlement, FinalSettlementLog, IncomeTaxSlab, ProfessionalTaxSlab, EmployeeStatutoryProfile). FinalSettlement FK uses `"app_exit.EmployeeExitRequest"`.
- 5b — code: `payroll_service`, `payroll_views`, `payslip_pdf`, `settlement_pdf`, `ctc`, `tds`, `professional_tax`, `ecr`, `esi_return`, `bank_file`; forms SalaryForm, StatutoryProfileForm, WageRegisterEntryRowForm (+ `WageRegisterFormSet`); views salary_update, salary_ctc_preview, statutory_profile_update, salary_slip_self/admin, wage_register_bulk, `_statutory_form_for`, `_profile_payroll_estimate`; templates payroll_cycle, payroll_employee, salary_admin, final_settlement, my_payslips, `_salary_block` (+ payroll index); tests: `test_payroll_*` (11), `test_payslip_pdf`, `test_phase2_salary`, `test_salary_form_3b` (they import each other as helpers, so move together and update `appEmp.` → `app_payroll.`).
- Watch: encrypted fields stay as `appEmp.fields.*` (table untouched, ciphertext unaffected); `rotate_encryption_keys` uses `apps.get_models()` so it picks up the move automatically; `payroll_views` imports `app_projects.filters` (app_payroll → app_projects is fine); `app_projects/test_wage_filters.py` imports Salary; `test_phase2_encryption/keys` stay in core but update imports.
- Smoke: payroll index/cycle/employee, payslip PDF, summary PDF, bank file, ECR, ESI return, final settlement + PDF, my payslips, salary save, CTC preview, statutory save, wage register.

### Phase 6 — core tidy-up (each item only with your OK)
- Aggregators (`dashboard_view` ≈ 830 lines, `context_processors`, profile pages): confirm all upward imports are lazy.
- Optionally turn `appEmp/views.py` and `forms.py` into packages by topic (employees, profile, dashboard, documents, bulk_import).
- Optionally move EmailOTP/WhatsAppOTP into appAuth.
- Observed, not touched: `urls.py` has duplicate entries for `employeeList` and `editAttendance`.

### Phase 7 — optional extractions (matches existing modules)
- `app_documents`: DocumentTypeMaster, empDocument, empDocumentForm, HrDocumentUploadForm, 5 views (module `documents`; BCAS requires it).
- `app_bulk_import`: EmployeeImportFieldConfig, EmployeeBulkImportForm, `employee_bulk_import_view` + its `_parse/_clean/_find_header` helpers (module `bulk_import`; used by `seed.py`, `app_projects/test_import.py`).

## 7. Known gotchas
- Table names have a capital E (`appEmp_...`); always copy from `_meta.db_table`.
- A remaining model FK'd to a moved model needs an `AlterField` inside `state_operations`.
- Circular imports (views ↔ new apps) are avoided by Phase 0 `access.py`.
- Meta (ordering, permissions, constraints, indexes) must be copied exactly; `makemigrations --check` shows drift if not.
- WhatsApp webhook path is external config: never change it.
- Payroll tests import each other; move as a set.

## 8. Status log
| Phase | Branch | Merged to main | Notes / deviations |
|---|---|---|---|
| 0 | | | |
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5a / 5b | | | |
| 6 | | | |
| 7 | | | |