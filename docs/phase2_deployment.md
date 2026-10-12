# Phase 2 deployment notes (encrypted personal data)

Applies to: appEmp migrations 0064 to 0070.
Assumes the app runs from a checkout of this repo on EC2, loads `.env.production`
(`DJANGO_ENV=production`), and uses PostgreSQL (local, or RDS).

## What changed and why it matters

Aadhaar, PAN, bank account, UAN, ESIC, phone and address are now stored
encrypted. Two secrets control this, and the app will not start without them:

- `FIELD_ENCRYPTION_KEYS`: one or more Fernet keys, comma separated, newest first.
  The first key encrypts. Every listed key can decrypt.
- `BLIND_INDEX_KEY`: a separate secret used for the fingerprints that make duplicate
  Aadhaar checks and phone search possible. At least 32 characters.

**If `FIELD_ENCRYPTION_KEYS` is lost, the encrypted data cannot be recovered.**
**If `BLIND_INDEX_KEY` is changed, every fingerprint stops matching.** Treat both as
long-lived secrets. A fingerprint rebuild is possible (values can still be
decrypted), but there is no command for it yet.

## Generating and storing the keys

Run once, on any machine with the project installed. Do not run it in a shared
terminal session or paste the output into chat, tickets or logs.

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    python -c "import secrets; print(secrets.token_urlsafe(48))"

The first command gives the encryption key, the second the blind-index key.

Where they live:

- On the server: only in `.env.production`, owned by the app user, `chmod 600`.
- A backup copy of both keys in a password manager or a secrets service (for
  example AWS Secrets Manager). **Keep it somewhere other than the database
  backups.** A backup that sits next to its own key protects nothing.
- Never in git. `.env.example` holds variable names with placeholder text only.

## Startup errors and what they mean

| Message starts with | Meaning |
|---|---|
| `FIELD_ENCRYPTION_KEYS is not set` | The variable is missing or empty in the env file the server loaded. Check `DJANGO_ENV=production` and the file name. |
| `FIELD_ENCRYPTION_KEYS entry #N is not a valid Fernet key` | Entry number N was mistyped or cut off. |
| `FIELD_ENCRYPTION_KEYS contains a duplicate key` | The same key appears twice. |
| `BLIND_INDEX_KEY is missing or shorter than 32 characters` | Missing, empty or too short. |
| `BLIND_INDEX_KEY must be different from every encryption key` | The two secrets must be different values. |

A value that cannot be decrypted at runtime raises an error that names the field and
row but never the value or a key. That means the wrong key is loaded or the stored
data is damaged.

## Deploying to an existing server that already has data

The migrations rename columns, so the old code cannot run against the new schema.
Plan for a short stop.

1. Stop the app (the way you normally do).
2. Back up, verify the backup, and copy it off the server:

        pg_dump -h DB_HOST -U DB_USER -Fc DB_NAME -f ~/before_phase2.dump
        pg_restore --list ~/before_phase2.dump | head -20

3. Add `FIELD_ENCRYPTION_KEYS` and `BLIND_INDEX_KEY` to `.env.production`.
4. Pull the code and install requirements. `cryptography` must be in
   `requirements.txt`.
5. Apply migrations and check:

        python manage.py migrate
        python manage.py check

6. Start the app.
7. Verify:

        python manage.py rotate_encryption_keys --dry-run

   Every field should report all values "already on newest key" and `rotated=0`.
   Then confirm the stored values are ciphertext:

        psql -h DB_HOST -U DB_USER DB_NAME -c "SELECT count(*) AS total, count(aadhar_no) AS aadhaar_set, count(*) FILTER (WHERE aadhar_no LIKE 'enc1:%') AS aadhaar_encrypted FROM \"appEmp_empprofile\";"

   `aadhaar_set` and `aadhaar_encrypted` must be equal. Then log in and check the HR
   employee list, a phone search, a profile edit and a bulk import preview.

Do not run `makemigrations` on the server.

### Rolling back

Restore the backup from step 2 and deploy the previous code. Do not use
`migrate appEmp 0065` for a rollback after real use: edits made after the switch
exist only in the encrypted columns, and the restored plain columns would be stale.

## Building a new RDS database

Do not run `migrate` on an empty RDS database and expect a working system. A fresh
database has no `yugaamAi` organization, so the copy-from-default steps for new
organizations have nothing to copy. Build it from a dump instead:

1. Create the RDS PostgreSQL instance (same major version as the source), turn on
   storage encryption at creation (it cannot be added later), keep automated
   backups on, and let the security group accept connections only from the EC2
   instance.
2. Create the database and user.
3. Take a custom-format dump from the source **after migration 0066 has been
   applied there**, then restore:

        pg_restore --no-owner --no-privileges -h RDS_HOST -U RDS_USER -d RDS_DB before_move.dump

4. Set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` in
   `.env.production`, with the **same** `FIELD_ENCRYPTION_KEYS` and
   `BLIND_INDEX_KEY` as the source. Different keys would make the data unreadable.
5. Run `python manage.py migrate`. It should report nothing to apply.
6. Run the verification in step 7 above.

If the connection fails with an SSL error, RDS is requiring SSL. The database
settings may then need `OPTIONS: {"sslmode": "require"}`.

## Rotating the encryption key

Reasons: a scheduled rotation, or someone who had access to the key leaving.

1. Generate a new key.
2. Put it **first** and keep the old one after it, for example
   `FIELD_ENCRYPTION_KEYS=NEWKEY,OLDKEY`, then restart every app process. Never
   replace the only key in place.
3. Back up the database.
4. Run `python manage.py rotate_encryption_keys --dry-run` and read the counts.
5. Run `python manage.py rotate_encryption_keys`. It runs in one transaction,
   re-encrypts each value, and rolls back if any value is not readable with the new
   key alone.
6. Run the dry run again. It must report `rotated=0`.
7. Keep the old key stored safely for as long as any backup made before the
   rotation might need restoring. Only then remove it from the env file.

`BLIND_INDEX_KEY` is not touched by rotation.

## Not finished yet

- Migration 0070 drops the old plain-text columns. It cannot be reversed from inside
  the database, so take the backup in step 2 before deploying.
- Database dumps made before this phase contain plain text. Keep them only as
  long as you need them, and protect or delete them after that.

## Tests

Run these on a development machine, not against the production database:

    python manage.py test appEmp.test_phase2_encryption
