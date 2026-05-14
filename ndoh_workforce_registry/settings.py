import os
import sys
from pathlib import Path

from django import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_list(name, default):
    value = os.environ.get(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(',') if item.strip()]


def _is_strong_secret_key(value):
    if not value or len(value) < 50:
        return False

    checks = [
        any(character.islower() for character in value),
        any(character.isupper() for character in value),
        any(character.isdigit() for character in value),
        len(set(value)) >= 12,
    ]
    return all(checks)


def _load_or_create_secret_key():
    secret_key_path = BASE_DIR / '.runtime_secret_key'
    if secret_key_path.exists():
        return secret_key_path.read_text(encoding='utf-8').strip()

    secret_key = get_random_secret_key()
    try:
        secret_key_path.write_text(secret_key, encoding='utf-8')
    except OSError:
        return secret_key
    return secret_key


DEBUG = _env_bool('DJANGO_DEBUG', _env_bool('DEBUG', True))
RUNNING_TESTS = 'test' in sys.argv

configured_secret_key = (os.environ.get('SECRET_KEY') or '').strip()
if configured_secret_key:
    if not DEBUG and not _is_strong_secret_key(configured_secret_key):
        raise ImproperlyConfigured('SECRET_KEY must be at least 50 characters and include varied characters.')
    SECRET_KEY = configured_secret_key
elif DEBUG:
    SECRET_KEY = _load_or_create_secret_key()
else:
    raise ImproperlyConfigured('SECRET_KEY must be set in non-debug environments.')

ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS', ['127.0.0.1', 'localhost', 'testserver'] if DEBUG else [])
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must be set when DEBUG=False.')
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS', [])

USE_HTTPS = _env_bool('USE_HTTPS', not DEBUG)
if RUNNING_TESTS:
    USE_HTTPS = False
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', USE_HTTPS)
CSRF_COOKIE_SECURE = _env_bool('CSRF_COOKIE_SECURE', USE_HTTPS)
SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', USE_HTTPS)
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000' if USE_HTTPS else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    'SECURE_HSTS_INCLUDE_SUBDOMAINS',
    USE_HTTPS and SECURE_HSTS_SECONDS > 0,
)
SECURE_HSTS_PRELOAD = _env_bool('SECURE_HSTS_PRELOAD', USE_HTTPS and SECURE_HSTS_SECONDS > 0)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.environ.get('SECURE_REFERRER_POLICY', 'same-origin')
SECURE_CROSS_ORIGIN_OPENER_POLICY = os.environ.get('SECURE_CROSS_ORIGIN_OPENER_POLICY', 'same-origin')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if _env_bool('SECURE_PROXY_SSL_HEADER', USE_HTTPS) else None
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
CSRF_COOKIE_HTTPONLY = _env_bool('CSRF_COOKIE_HTTPONLY', False)
CSRF_COOKIE_SAMESITE = os.environ.get('CSRF_COOKIE_SAMESITE', 'Lax')
X_FRAME_OPTIONS = os.environ.get('X_FRAME_OPTIONS', 'DENY')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'import_export',

    # Local apps
    'apps.accounts',
    'apps.documents',
    'apps.workforce',
    'apps.competency',
    'apps.notifications',
    'apps.ocr',
    'apps.dashboard',
    'apps.common',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'ndoh_workforce_registry.middleware.StaffMFAMiddleware',
    'ndoh_workforce_registry.middleware.IdleSessionTimeoutMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ndoh_workforce_registry.urls'
CELERY_BROKER_URL = 'redis://localhost:6379/0'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.dashboard.context_processors.portal_access',
                'apps.notifications.context_processors.staff_notifications',
              ],
        },
    },
]

WSGI_APPLICATION = 'ndoh_workforce_registry.wsgi.application'

DATABASE_ENGINE = os.environ.get('DATABASE_ENGINE')
if not DATABASE_ENGINE:
    DATABASE_ENGINE = 'postgresql' if (os.environ.get('DB_NAME') or not DEBUG) else 'sqlite'
DATABASE_ENGINE = DATABASE_ENGINE.strip().lower()

if DATABASE_ENGINE == 'sqlite':
    if not DEBUG and not _env_bool('ALLOW_SQLITE_IN_PRODUCTION', False):
        raise ImproperlyConfigured('SQLite is disabled when DEBUG=False. Configure PostgreSQL for production.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('SQLITE_NAME', BASE_DIR / 'db.sqlite3'),
        }
    }
else:
    required_database_settings = ['DB_NAME', 'DB_USER', 'DB_PASSWORD']
    missing_database_settings = [name for name in required_database_settings if not os.environ.get(name)]
    if not DEBUG and missing_database_settings:
        missing = ', '.join(missing_database_settings)
        raise ImproperlyConfigured(f'Missing required database environment variables: {missing}.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5433'),
        }
    }

AUTH_USER_MODEL = 'accounts.User'
LOGIN_REDIRECT_URL = '/accounts/profile/'
LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
PASSWORD_RESET_TIMEOUT = int(os.environ.get('PASSWORD_RESET_TIMEOUT', '3600'))
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
SESSION_COOKIE_AGE = 900
SESSION_SAVE_EVERY_REQUEST = True
REQUIRE_STAFF_MFA = _env_bool('REQUIRE_STAFF_MFA', False)
STAFF_MFA_TIMEOUT_SECONDS = int(os.environ.get('STAFF_MFA_TIMEOUT_SECONDS', '600'))
STAFF_MFA_ROLES = tuple(_env_list('STAFF_MFA_ROLES', ['admin', 'registrar']))
AI_ASSISTANT_PROVIDER = os.environ.get('AI_ASSISTANT_PROVIDER', 'local').lower()
AI_ASSISTANT_EXTERNAL_ENABLED = _env_bool('AI_ASSISTANT_EXTERNAL_ENABLED', False)
AI_ASSISTANT_LOCAL_LLM_ENABLED = _env_bool('AI_ASSISTANT_LOCAL_LLM_ENABLED', False)
AI_ASSISTANT_OLLAMA_ENABLED = _env_bool('AI_ASSISTANT_OLLAMA_ENABLED', False)
AI_IMPORT_CLEANSING_EXTERNAL_ENABLED = _env_bool('AI_IMPORT_CLEANSING_EXTERNAL_ENABLED', False)
AI_IMPORT_CLEANSING_MODEL_ENABLED = _env_bool('AI_IMPORT_CLEANSING_MODEL_ENABLED', False)
AI_ASSISTANT_TIMEOUT_SECONDS = int(os.environ.get('AI_ASSISTANT_TIMEOUT_SECONDS', '20'))
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.4-mini')
AI_LOCAL_LLM_BASE_URL = os.environ.get('AI_LOCAL_LLM_BASE_URL', '')
AI_LOCAL_LLM_API_KEY = os.environ.get('AI_LOCAL_LLM_API_KEY', '')
AI_LOCAL_LLM_MODEL = os.environ.get('AI_LOCAL_LLM_MODEL', '')
AI_OLLAMA_BASE_URL = os.environ.get('AI_OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
AI_OLLAMA_MODEL = os.environ.get('AI_OLLAMA_MODEL', '')
AI_OLLAMA_KEEP_ALIVE = os.environ.get('AI_OLLAMA_KEEP_ALIVE', '10m')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = Path(os.environ.get('STATIC_ROOT', BASE_DIR / 'staticfiles'))

MEDIA_URL = os.environ.get('MEDIA_URL', '/media/')
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', BASE_DIR / 'media'))

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email Configuration (use your real SMTP settings in production)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'          # or your SMTP server
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg')
CSRF_FAILURE_VIEW = 'ndoh_workforce_registry.views.csrf_failure'
