import os
import ipaddress
import socket
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


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_list(name, default):
    value = os.environ.get(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(',') if item.strip()]


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _local_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            value = info[4][0]
            ip = ipaddress.ip_address(value)
            if ip.is_private or ip.is_loopback:
                addresses.append(value)
    except OSError:
        pass
    return _dedupe(addresses)


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
LOCAL_MOBILE_TESTING = DEBUG and _env_bool('LOCAL_MOBILE_TESTING', True)

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

LOCAL_MOBILE_TEST_HOSTS = []
if LOCAL_MOBILE_TESTING:
    LOCAL_MOBILE_TEST_HOSTS = _dedupe([
        '127.0.0.1',
        'localhost',
        'testserver',
        '10.0.2.2',
        # Hotspot demos can expose the laptop on a different private IPv4
        # than the adapter currently reports, so keep the known tablet path.
        '192.168.8.101',
        *_local_ipv4_addresses(),
    ])
    ALLOWED_HOSTS = _dedupe([*ALLOWED_HOSTS, *LOCAL_MOBILE_TEST_HOSTS])
    CSRF_TRUSTED_ORIGINS = _dedupe([
        *CSRF_TRUSTED_ORIGINS,
        *[
            f'http://{host}:8000'
            for host in LOCAL_MOBILE_TEST_HOSTS
            if host != 'testserver'
        ],
    ])

PLATFORM_DEPLOYMENT_MODE = os.environ.get('PLATFORM_DEPLOYMENT_MODE', 'auto').strip().lower()
if PLATFORM_DEPLOYMENT_MODE not in {'auto', 'online', 'offline_lan'}:
    PLATFORM_DEPLOYMENT_MODE = 'auto'
PLATFORM_OFFLINE_LAN_ENABLED = _env_bool('PLATFORM_OFFLINE_LAN_ENABLED', True)
PLATFORM_FORCE_OFFLINE = _env_bool('PLATFORM_FORCE_OFFLINE', False)
PLATFORM_AUTO_SYNC_ENABLED = _env_bool('PLATFORM_AUTO_SYNC_ENABLED', True)
PLATFORM_CONNECTIVITY_CHECK_URLS = _env_list(
    'PLATFORM_CONNECTIVITY_CHECK_URLS',
    [
        'https://www.health.gov.pg/index.html',
        'https://www.google.com/generate_204',
    ],
)
PLATFORM_CONNECTIVITY_TIMEOUT_SECONDS = _env_float('PLATFORM_CONNECTIVITY_TIMEOUT_SECONDS', 3.0)
PLATFORM_SYNC_REMOTE_URL = os.environ.get('PLATFORM_SYNC_REMOTE_URL', '').strip()
PLATFORM_SYNC_API_KEY = os.environ.get('PLATFORM_SYNC_API_KEY', '').strip()
PLATFORM_SYNC_WORKER_INTERVAL_SECONDS = int(os.environ.get('PLATFORM_SYNC_WORKER_INTERVAL_SECONDS', '60'))
PLATFORM_SYNC_WORKER_BATCH_SIZE = int(os.environ.get('PLATFORM_SYNC_WORKER_BATCH_SIZE', '25'))

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
    'apps.complaints',
    'apps.board_portal',
    'apps.ocr',
    'apps.dashboard',
    'apps.common',
    'apps.mobile_intake',
    'apps.nhwa_workbooks',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'NDOH_regulatory_bodies.middleware.StaffMFAMiddleware',
    'NDOH_regulatory_bodies.middleware.IdleSessionTimeoutMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'NDOH_regulatory_bodies.urls'
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

WSGI_APPLICATION = 'NDOH_regulatory_bodies.wsgi.application'

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
AI_GOOGLE_ADK_ENABLED = _env_bool('AI_GOOGLE_ADK_ENABLED', False)
AI_ASSISTANT_LOCALAI_ENABLED = _env_bool('AI_ASSISTANT_LOCALAI_ENABLED', False)
AI_REDIS_WORKER_ENABLED = _env_bool('AI_REDIS_WORKER_ENABLED', False)
AI_IMPORT_CLEANSING_EXTERNAL_ENABLED = _env_bool('AI_IMPORT_CLEANSING_EXTERNAL_ENABLED', False)
AI_IMPORT_CLEANSING_MODEL_ENABLED = _env_bool('AI_IMPORT_CLEANSING_MODEL_ENABLED', False)
AI_ASSISTANT_TIMEOUT_SECONDS = int(os.environ.get('AI_ASSISTANT_TIMEOUT_SECONDS', '20'))
AI_REDIS_URL = os.environ.get('AI_REDIS_URL', os.environ.get('CELERY_BROKER_URL', CELERY_BROKER_URL))
AI_REDIS_WORKER_QUEUE = os.environ.get('AI_REDIS_WORKER_QUEUE', 'staff_ai_requests')
AI_REDIS_WORKER_RESULT_PREFIX = os.environ.get('AI_REDIS_WORKER_RESULT_PREFIX', 'staff_ai_result:')
AI_REDIS_WORKER_TIMEOUT_SECONDS = int(os.environ.get('AI_REDIS_WORKER_TIMEOUT_SECONDS', '25'))
AI_REDIS_WORKER_RESULT_TTL_SECONDS = int(os.environ.get('AI_REDIS_WORKER_RESULT_TTL_SECONDS', '120'))
AI_REDIS_WORKER_SOCKET_TIMEOUT_SECONDS = int(os.environ.get('AI_REDIS_WORKER_SOCKET_TIMEOUT_SECONDS', '5'))
AI_REDIS_WORKER_MODEL_PROVIDER = os.environ.get('AI_REDIS_WORKER_MODEL_PROVIDER', 'local').lower()
AI_REDIS_WORKER_MODEL_BASE_URL = os.environ.get('AI_REDIS_WORKER_MODEL_BASE_URL', '')
AI_REDIS_WORKER_MODEL_API_KEY = os.environ.get('AI_REDIS_WORKER_MODEL_API_KEY', '')
AI_REDIS_WORKER_MODEL = os.environ.get('AI_REDIS_WORKER_MODEL', '')
AI_REDIS_WORKER_MODEL_TIMEOUT_SECONDS = int(os.environ.get('AI_REDIS_WORKER_MODEL_TIMEOUT_SECONDS', '30'))
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.4-mini')
NURSING_COUNCIL_BOARD_REGISTRATION_TOKEN = os.environ.get('NURSING_COUNCIL_BOARD_REGISTRATION_TOKEN', '').strip()
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
AI_GOOGLE_ADK_MODEL = os.environ.get('AI_GOOGLE_ADK_MODEL', 'gemini-flash-latest')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
GOOGLE_GEOCODING_API_KEY = os.environ.get('GOOGLE_GEOCODING_API_KEY', GOOGLE_MAPS_API_KEY)
AI_LOCAL_LLM_BASE_URL = os.environ.get('AI_LOCAL_LLM_BASE_URL', '')
AI_LOCAL_LLM_API_KEY = os.environ.get('AI_LOCAL_LLM_API_KEY', '')
AI_LOCAL_LLM_MODEL = os.environ.get('AI_LOCAL_LLM_MODEL', '')
AI_LOCALAI_BASE_URL = os.environ.get('AI_LOCALAI_BASE_URL', 'http://127.0.0.1:8080')
AI_LOCALAI_API_KEY = os.environ.get('AI_LOCALAI_API_KEY', '')
AI_LOCALAI_MODEL = os.environ.get('AI_LOCALAI_MODEL', '')
AI_OLLAMA_BASE_URL = os.environ.get('AI_OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
AI_OLLAMA_MODEL = os.environ.get('AI_OLLAMA_MODEL', '')
AI_OLLAMA_KEEP_ALIVE = os.environ.get('AI_OLLAMA_KEEP_ALIVE', '10m')
AI_OLLAMA_NUM_PREDICT = int(os.environ.get('AI_OLLAMA_NUM_PREDICT', '240'))
AI_OLLAMA_NUM_CTX = int(os.environ.get('AI_OLLAMA_NUM_CTX', '2048'))
AI_ASSISTANT_RAG_ENABLED = _env_bool('AI_ASSISTANT_RAG_ENABLED', False)
AI_ASSISTANT_RAG_AUTO_BUILD = _env_bool('AI_ASSISTANT_RAG_AUTO_BUILD', True)
if RUNNING_TESTS:
    # A developer's local RAG configuration must not cause the test suite to
    # download embedding models or depend on network access. Individual RAG
    # tests opt in explicitly with override_settings and mocked embeddings.
    AI_ASSISTANT_RAG_ENABLED = False
    AI_ASSISTANT_RAG_AUTO_BUILD = False
AI_ASSISTANT_RAG_INDEX_PATH = os.environ.get(
    'AI_ASSISTANT_RAG_INDEX_PATH',
    str(BASE_DIR / 'media' / 'ai_knowledge' / 'staff_assistant_index.json'),
)
AI_ASSISTANT_RAG_VECTOR_BACKEND = os.environ.get('AI_ASSISTANT_RAG_VECTOR_BACKEND', 'local_json').lower()
AI_ASSISTANT_CHROMA_PATH = os.environ.get(
    'AI_ASSISTANT_CHROMA_PATH',
    str(BASE_DIR / 'media' / 'ai_knowledge' / 'chroma'),
)
AI_ASSISTANT_CHROMA_COLLECTION = os.environ.get('AI_ASSISTANT_CHROMA_COLLECTION', 'staff_assistant_knowledge')
AI_ASSISTANT_RAG_MAX_DOCUMENTS = int(os.environ.get('AI_ASSISTANT_RAG_MAX_DOCUMENTS', '800'))
AI_ASSISTANT_RAG_MIN_SCORE = float(os.environ.get('AI_ASSISTANT_RAG_MIN_SCORE', '0.18'))
AI_ASSISTANT_EMBEDDING_MODEL = os.environ.get(
    'AI_ASSISTANT_EMBEDDING_MODEL',
    'sentence-transformers/all-MiniLM-L6-v2',
)
AI_ASSISTANT_EMBEDDING_LOCAL_FILES_ONLY = _env_bool('AI_ASSISTANT_EMBEDDING_LOCAL_FILES_ONLY', True)

# Regulatory ML is deliberately aggregate-only by default.  These controls
# keep forecasting and data-quality scoring local, bounded, and separate from
# approval workflows or raw-chat training.
REGULATORY_ML_ENABLED = _env_bool('REGULATORY_ML_ENABLED', True)
REGULATORY_ML_USE_SCIKIT_LEARN = _env_bool('REGULATORY_ML_USE_SCIKIT_LEARN', True)
REGULATORY_ML_ALLOW_TRAINING = _env_bool('REGULATORY_ML_ALLOW_TRAINING', False)
REGULATORY_ML_CACHE_SECONDS = int(os.environ.get('REGULATORY_ML_CACHE_SECONDS', '300'))
REGULATORY_ML_FORECAST_HORIZON_YEARS = int(os.environ.get('REGULATORY_ML_FORECAST_HORIZON_YEARS', '10'))
REGULATORY_ML_MIN_TRAINING_OBSERVATIONS = int(os.environ.get('REGULATORY_ML_MIN_TRAINING_OBSERVATIONS', '8'))

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

# Email Configuration (console backend is safe for local integrated testing)
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')          # or your SMTP server
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@ndoh.gov.pg')
CSRF_FAILURE_VIEW = 'NDOH_regulatory_bodies.views.csrf_failure'
