
import os
from pathlib import Path

from dotenv import load_dotenv


# =========================================================
# Base Directory
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# =========================================================
# Environment Variables
# =========================================================

# =========================================================
# Environment Variables
# =========================================================

DJANGO_ENV = os.environ.get("DJANGO_ENV", "local")  # "local" or "production"
env_file = ".env.production" if DJANGO_ENV == "production" else ".env"
load_dotenv(BASE_DIR / env_file)


# =========================================================
# Field Encryption Keys (Phase 2)
# =========================================================

# Newest key first. The first key encrypts; every key can decrypt.
FIELD_ENCRYPTION_KEYS = [
    key.strip()
    for key in os.environ.get("FIELD_ENCRYPTION_KEYS", "").split(",")
    if key.strip()
]
# Separate secret used only for blind-index fingerprints.
BLIND_INDEX_KEY = os.environ.get("BLIND_INDEX_KEY", "").strip()


def _validate_field_keys():
    # Fail loudly at startup. Never put a key value in an error message.
    from cryptography.fernet import Fernet
    from django.core.exceptions import ImproperlyConfigured

    if not FIELD_ENCRYPTION_KEYS:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is not set. Generate a key once with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())' and add it to your env "
            "file. Back it up outside the server: if it is lost, encrypted "
            "data cannot be recovered."
        )
    for position, key in enumerate(FIELD_ENCRYPTION_KEYS, start=1):
        try:
            Fernet(key.encode())
        except (ValueError, TypeError):
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEYS entry #%d is not a valid Fernet key." % position
            ) from None
    if len(set(FIELD_ENCRYPTION_KEYS)) != len(FIELD_ENCRYPTION_KEYS):
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS contains a duplicate key.")
    if len(BLIND_INDEX_KEY) < 32:
        raise ImproperlyConfigured(
            "BLIND_INDEX_KEY is missing or shorter than 32 characters."
        )
    if BLIND_INDEX_KEY in FIELD_ENCRYPTION_KEYS:
        raise ImproperlyConfigured(
            "BLIND_INDEX_KEY must be different from every encryption key."
        )


_validate_field_keys()


# =========================================================
# Security
# =========================================================

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-development-key"
)

DEBUG = (
    os.environ.get("DJANGO_DEBUG", "False").lower()
    == "true"
)


ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "127.0.0.1,localhost"
    ).split(",")
    if host.strip()
]


CSRF_TRUSTED_ORIGINS = [
    "http://18.61.200.14:8001",
    "https://numa-hr.com",
    "https://www.numa-hr.com",
    "http://16.113.71.212",
]



# =========================================================
# Applications
# =========================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "storages",


    "appAuth",
    "appEmp",
    "app_organizations",
    "app_projects",
]


# =========================================================
# Middleware
# =========================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",

    "django.middleware.common.CommonMiddleware",

    "django.middleware.csrf.CsrfViewMiddleware",

    "django.contrib.auth.middleware.AuthenticationMiddleware",

    "app_organizations.middleware.CurrentOrganizationMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",

    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =========================================================
# URLs / WSGI
# =========================================================

ROOT_URLCONF = "projSkySource.urls"

WSGI_APPLICATION = "projSkySource.wsgi.application"
SECURE_SSL_REDIRECT = DJANGO_ENV == "production"
SESSION_COOKIE_SECURE = DJANGO_ENV == "production"
CSRF_COOKIE_SECURE = DJANGO_ENV == "production"

# =========================================================
# Templates
# =========================================================

TEMPLATES = [
    {
        "BACKEND": (
            "django.template.backends.django."
            "DjangoTemplates"
        ),

        "DIRS": [
            BASE_DIR / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",

                "django.contrib.auth."
                "context_processors.auth",

                "django.contrib.messages."
                "context_processors.messages",

                "appEmp.context_processors.user_role",
                "app_projects.context_processors.project_nav",
            ],
        },
    },
]


# =========================================================
# Database
# =========================================================

# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.sqlite3",
#         "NAME": BASE_DIR / "db.sqlite3",
#     }
# }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME"),
        "USER": os.environ.get("DB_USER"),
        "PASSWORD": os.environ.get("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST"),
        "PORT": os.environ.get("DB_PORT"),
        "TEST": {"NAME": "test_projskysource"},
    }
}


# =========================================================
# Password Validation
# =========================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# =========================================================
# Internationalization
# =========================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Kolkata"

USE_I18N = True

USE_TZ = True
AZURE_EMAIL_CONNECTION_STRING = os.getenv("AZURE_EMAIL_CONNECTION_STRING")
AZURE_EMAIL_SENDER = os.getenv("AZURE_EMAIL_SENDER")

# =========================================================
# Authentication Redirects
# =========================================================

LOGIN_REDIRECT_URL = "/emp/dashboard/"
LOGIN_URL = "/app/login/"



# =========================================================
# Static Files
# =========================================================

STATIC_URL = "/static/"
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
PRIVATE_MEDIA_ROOT = BASE_DIR / 'private_media'

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"


# =========================================================
# Default Primary Key
# =========================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')
WHATSAPP_VERIFY_TOKEN = os.environ.get('WHATSAPP_VERIFY_TOKEN')

# =========================================================
# File Storage (S3)
# =========================================================

USE_S3 = os.environ.get("USE_S3", "False") == "True"

if USE_S3:
    AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME")
    AWS_S3_ENDPOINT_URL = f"https://s3.{AWS_S3_REGION_NAME}.amazonaws.com"
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


LITE_SIGNUP_URL = "https://lite.numa-hr.com/register/"
LITE_LOGIN_URL = "https://lite.numa-hr.com/login/"
