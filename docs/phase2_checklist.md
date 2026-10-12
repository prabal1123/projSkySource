# Phase 2 checklist (encryption of personal and salary data)

## Done

- [x] Keys: `FIELD_ENCRYPTION_KEYS` (Fernet, newest first) and a separate
      `BLIND_INDEX_KEY`; the app refuses to start if either is missing or invalid.
- [x] Encrypted field types (text, multi-line text, decimal); stored values start
      with `enc1:`.
- [x] Fingerprints for Aadhaar (unique across all organizations) and phone.
- [x] Personal fields encrypted: Aadhaar, PAN, bank account, UAN, ESIC, phone,
      address (migrations 0064 to 0066).
- [x] Salary figures encrypted: Salary basic, HRA, PF and daily rate, and the
      wage register rate override (migrations 0067 to 0069).
- [x] Code paths moved off plain columns: duplicate Aadhaar checks, HR phone search
      (full number only), WhatsApp router, admin search.
- [x] Admin lockdown: only superusers see and edit the seven personal fields.
- [x] Duplicate Aadhaar gives a plain form error; bulk import skips a row the
      database refuses and carries on.
- [x] `rotate_encryption_keys` command (with `--dry-run`).
- [x] Fresh-database fix in migration 0056, so an empty database migrates.
- [x] Tests: `python manage.py test appEmp.test_phase2_salary appEmp.test_phase2_encryption`
      (23 tests).
- [x] Deployment notes: `docs/phase2_deployment.md`.

## Must be true before the final cleanup

- [x] Real-page check passed: HR employee list and phone search, profile edit,
      bulk import preview and confirm, salary page, salary edit, wage register
      screen, payslip PDF.
- [x] Fresh backup taken and checked with `pg_restore --list`.
- [x] Tests pass.

## Final cleanup (migration 0070): drop the old plain-text columns

Drops 12 columns. The app does not use them, but they still hold the original
readable values, so until they are gone the encryption does not protect data
at rest.

- Personal: `aadhar_no_legacy`, `pan_no_legacy`, `bank_account_no_legacy`,
  `uan_no_legacy`, `esic_no_legacy`, `phone_number_legacy`, `address_legacy`
- Salary and wage: `basic_salary_legacy`, `hra_legacy`, `pf_legacy`,
  `daily_rate_legacy`, `rate_override_legacy`

This cannot be undone from inside the database; the only way back is a backup.

- [x] Migration 0070 written and applied
- [x] Models cleaned (the legacy field lines removed)
- [x] Tests pass and pages checked again
- [ ] Old plain-text dumps deleted from `~/db_backups/` once you are sure
      (`postgres_before_phase2_5a.dump`, `postgres_before_phase2_5b.dump`,
      `postgres_before_salary_enc.dump`, and any older ones)

## Before the first production release

`.github/workflows/deploy.yml` deploys on every push to `main` and runs `migrate`
with no backup and no key check. **Do not push `main` until these are done.**

- [ ] `deploy.yml`: add `script_stop: true` so a failed step stops the deploy.
- [ ] `deploy.yml`: stop the deploy when `FIELD_ENCRYPTION_KEYS` or
      `BLIND_INDEX_KEY` is missing on the server.
- [ ] Consider a manual trigger for this one release.
- [ ] Confirm the deploy shell loads `DJANGO_ENV=production`, so `.env.production`
      is the file that is read.
- [ ] Both keys are in `.env.production` and stored elsewhere (not with the
      database backups).
- [ ] RDS snapshot and a dump taken; all migrations tested on a restored copy of
      the production data (row counts match, no NULL organizations).
- [ ] Follow `docs/phase2_deployment.md` for the order of steps.

## Carried over from earlier

- [ ] Phase 1 regression scripts (17 of 17, 18 of 18) are not in the repo.
- [ ] WhatsApp router: one number for all organizations, or one per organization.
- [ ] OTP generator uses `random`.
- [ ] `/emp/dashboard/` returns 404 for a user with no profile.
- [ ] Delete the "Test Dup" holiday in `yugaamAi`.
- [ ] Airport table is empty (BCAS needs airports added).
- [ ] Check-in with location and the plain-employee dashboard were never tested.
