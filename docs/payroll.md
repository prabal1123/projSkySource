# Payroll (monthly-wage employees)

Daily-wage staff stay on the **Wage Register**. Everyone on a `MONTHLY` salary
goes through the payroll screens described here.

Payroll is a sellable module. An organization needs the `payroll` module (which
also brings `attendance`); otherwise every payroll URL returns 403 and the
sidebar links are hidden. The URL names are listed under `payroll` in
`app_organizations/modules.py`.

## Who can do what

| Who | Can |
|---|---|
| Users with `manage_salary` (and superusers) | Open **Payroll**, calculate, lock/unlock, download any payslip and the month summary |
| Every employee | Open **My Payslips** and download their own *locked* payslips |

Everything is scoped to the signed-in user's current organization. Unlocking is
open to anyone with `manage_salary`.

## Monthly workflow

1. **Payroll** (sidebar) opens the month that just ended. Use the month picker and
   the project filter to change what is in view.
2. **Calculate & save drafts** stores a draft for everyone in view.
3. Review each employee (click the name for the day-by-day breakdown). Fix
   attendance or leave if needed and recalculate.
4. **Lock month** freezes the figures. Only possible once the month has ended.
   After locking, employees can see and download their payslip.
5. **Summary PDF** gives the month register for the locked records in view.
6. **Unlock** withdraws a payslip so figures can be corrected, then lock again.

Locked figures never change on their own. If attendance or leave is edited after
locking, the row shows a **Changed since lock** badge but keeps the locked amounts.

## How pay is calculated

For each calendar day, first match wins:

| Day | Counts as |
|---|---|
| Before joining date / after the final working day of a completed exit | Not employed (not paid) |
| Weekly off in the employee's `WorkSchedule` | Paid |
| Mandatory holiday, or approved optional holiday | Paid |
| Approved full-day leave | Paid or loss of pay, per the leave type's `is_paid` |
| Approved half-day leave | That half per `is_paid`; other half follows attendance |
| Attendance `PRESENT` / `LATE` | Paid |
| Attendance `HALF_DAY` | Half paid, half loss of pay |
| Attendance `LEAVE` without an approved request | Paid, with a warning |
| Attendance `ABSENT`, or no record for a day that is over | Loss of pay |
| No record, day not yet over | Assumed payable; month is **provisional** |

```
payable days = days employed in the month - loss-of-pay days
gross earned = (basic + HRA) x payable days / days in month
net pay      = gross earned - PF - ESI - other deductions - TDS      (never below 0)
```

PF, ESI and other deductions are the fixed monthly amounts on the salary and are
**not** pro-rated. TDS is the existing monthly figure on the full gross. The salary
revision used is the latest one effective on or before the month end.

## Where things live

| Area | File |
|---|---|
| Calculation (no HTTP, one code path for one or many employees) | `appEmp/payroll_service.py` |
| Screens and actions | `appEmp/payroll_views.py` |
| Payslip and summary PDFs (ReportLab) | `appEmp/payslip_pdf.py` |
| Frozen monthly snapshot | `PayrollRecord` in `appEmp/models.py` (amounts are encrypted like `Salary`) |
| Templates | `templates/appEmp/payroll_cycle.html`, `payroll_employee.html`, `my_payslips.html` |
| URLs | `payroll/`, `payroll/<year>/<month>/`, `.../<uuid>/`, `.../<uuid>/payslip/`, `.../summary/`, `my-payslips/`, `my-payslips/<year>/<month>/` |

`PayrollRecord` amounts are encrypted, so sum them in Python rather than with
database aggregates.

## The old salary slip

The previous slip printed the current salary for any month and ignored attendance.
It has been removed. Its URLs (`salarySlipSelf`, `salarySlipAdmin`) still exist and
now redirect to the finalised payslip, or explain that payroll has not been
finalised for that month.

## Tests

```
python manage.py test appEmp.test_payroll_models appEmp.test_payroll_service appEmp.test_payroll_views appEmp.test_payslip_pdf appEmp.test_payroll_pdf appEmp.test_payroll_integration app_organizations.test_module_gate
```
