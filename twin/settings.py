"""Django settings. Everything environment-specific comes from env vars."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
# The insecure key is only a convenience for debug runs; otherwise it must be set.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-insecure-key-change-me" if DEBUG else None
)
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is not 1.")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# LAN mode (M4): off unless TWIN_LAN_HOST is set (the computer's address on a trusted home
# network, e.g. 192.168.1.20). docker-compose.yml binds the port to it; otherwise 127.0.0.1 only.
# HTTP only until M6 adds HTTPS, so never with debug on.
TWIN_LAN_HOST = os.environ.get("TWIN_LAN_HOST", "").strip()
CSRF_TRUSTED_ORIGINS = []
if TWIN_LAN_HOST:
    if DEBUG:
        raise ImproperlyConfigured(
            "LAN mode (TWIN_LAN_HOST) refuses to start while DJANGO_DEBUG=1; debug is for local development only."
        )
    if TWIN_LAN_HOST not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(TWIN_LAN_HOST)
    CSRF_TRUSTED_ORIGINS.append(f"http://{TWIN_LAN_HOST}:8000")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "ui",
    # UI modules (each ships a module.json manifest; ui/modules.py is the registry).
    "modules.probes",
    "modules.zone",
    "modules.training",
    "backup",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files (admin and app) with debug off; no CDN.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "twin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "twin.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "twin"),
        "USER": os.environ.get("POSTGRES_USER", "twin"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Serve straight from the app folders (no collectstatic step needed for a personal instance).
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

# Phone app (M4): one contributor per instance in Nymbus phase 1; every login sees this one.
TWIN_CONTRIBUTOR = os.environ.get("TWIN_CONTRIBUTOR", "mike")
LOGIN_URL = "ui:login"
LOGIN_REDIRECT_URL = "ui:home"
LOGOUT_REDIRECT_URL = "ui:login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# Login rate limit: after this many failed attempts for one username or one address,
# further attempts are refused for the window (ui/views.py, LoginView).
# Encrypted off-hours backup (M4.5). The rclone config path comes from RCLONE_CONFIG (set by the
# backup service from RCLONE_CONFIG_HOST); BACKUP_REMOTE names the crypt remote, e.g. "twin-crypt:".
BACKUP_REMOTE = os.environ.get("BACKUP_REMOTE", "").strip()
BACKUP_WINDOW = os.environ.get("BACKUP_WINDOW", "02:00-05:00")
BACKUP_INCLUDE_INBOX = os.environ.get("BACKUP_INCLUDE_INBOX", "0") == "1"
BACKUP_INBOX_DIR = BASE_DIR / "data" / "inbox"
TWIN_VERSION = "0.4.0"  # app version recorded in backup manifests
TWIN_LOGIN_MAX_FAILURES = 5
TWIN_LOGIN_WINDOW_SECONDS = 15 * 60
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
