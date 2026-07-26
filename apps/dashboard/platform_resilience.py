import json
import socket
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, ProgrammingError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import PlatformConnectivityState, PlatformSyncOutboxItem


CONNECTIVITY_CACHE_KEY = 'platform_resilience_status'
PLATFORM_STATE_KEY = 'platform'


class PlatformSyncError(Exception):
    pass


def _setting(name, default=None):
    return getattr(settings, name, default)


def _datetime_payload(value):
    if not value:
        return ''
    return timezone.localtime(value).isoformat()


def _fallback_status(message='Connectivity state has not been initialised.'):
    deployment_mode = _setting('PLATFORM_DEPLOYMENT_MODE', 'auto')
    forced_offline = bool(_setting('PLATFORM_FORCE_OFFLINE', False))
    mode = PlatformConnectivityState.MODE_OFFLINE_LAN if forced_offline else PlatformConnectivityState.MODE_UNKNOWN
    if deployment_mode == 'online' and not forced_offline:
        mode = PlatformConnectivityState.MODE_ONLINE
    if deployment_mode == 'offline_lan':
        mode = PlatformConnectivityState.MODE_OFFLINE_LAN
    return {
        'mode': mode,
        'mode_label': 'Offline LAN' if mode == PlatformConnectivityState.MODE_OFFLINE_LAN else mode.title(),
        'is_online': mode == PlatformConnectivityState.MODE_ONLINE and not forced_offline,
        'is_offline_lan': mode == PlatformConnectivityState.MODE_OFFLINE_LAN,
        'forced_offline': forced_offline,
        'deployment_mode': deployment_mode,
        'offline_lan_enabled': bool(_setting('PLATFORM_OFFLINE_LAN_ENABLED', True)),
        'auto_sync_enabled': bool(_setting('PLATFORM_AUTO_SYNC_ENABLED', True)),
        'sync_remote_configured': bool(_setting('PLATFORM_SYNC_REMOTE_URL', '')),
        'pending_sync_count': 0,
        'failed_sync_count': 0,
        'blocked_sync_count': 0,
        'last_checked_at': '',
        'last_online_at': '',
        'last_offline_at': '',
        'last_successful_url': '',
        'last_error': message,
        'consecutive_successes': 0,
        'consecutive_failures': 0,
    }


def _status_from_state(state):
    effective_forced_offline = bool(state.forced_offline or _setting('PLATFORM_FORCE_OFFLINE', False))
    effective_sync_enabled = bool(state.sync_enabled and _setting('PLATFORM_AUTO_SYNC_ENABLED', True))
    mode = PlatformConnectivityState.MODE_OFFLINE_LAN if effective_forced_offline else state.mode
    try:
        pending_count = PlatformSyncOutboxItem.objects.filter(status=PlatformSyncOutboxItem.STATUS_PENDING).count()
        failed_count = PlatformSyncOutboxItem.objects.filter(status=PlatformSyncOutboxItem.STATUS_FAILED).count()
        blocked_count = PlatformSyncOutboxItem.objects.filter(status=PlatformSyncOutboxItem.STATUS_BLOCKED).count()
    except (OperationalError, ProgrammingError):
        pending_count = failed_count = blocked_count = 0
    return {
        'mode': mode,
        'mode_label': 'Offline LAN' if mode == PlatformConnectivityState.MODE_OFFLINE_LAN else state.get_mode_display(),
        'is_online': mode == PlatformConnectivityState.MODE_ONLINE and not effective_forced_offline,
        'is_offline_lan': mode == PlatformConnectivityState.MODE_OFFLINE_LAN,
        'forced_offline': effective_forced_offline,
        'deployment_mode': _setting('PLATFORM_DEPLOYMENT_MODE', 'auto'),
        'offline_lan_enabled': bool(_setting('PLATFORM_OFFLINE_LAN_ENABLED', True)),
        'auto_sync_enabled': effective_sync_enabled,
        'sync_remote_configured': bool(_setting('PLATFORM_SYNC_REMOTE_URL', '')),
        'pending_sync_count': pending_count,
        'failed_sync_count': failed_count,
        'blocked_sync_count': blocked_count,
        'last_checked_at': _datetime_payload(state.last_checked_at),
        'last_online_at': _datetime_payload(state.last_online_at),
        'last_offline_at': _datetime_payload(state.last_offline_at),
        'last_successful_url': state.last_successful_url,
        'last_error': state.last_error,
        'consecutive_successes': state.consecutive_successes,
        'consecutive_failures': state.consecutive_failures,
    }


def current_platform_status(use_cache=True):
    if use_cache:
        cached = cache.get(CONNECTIVITY_CACHE_KEY)
        if cached:
            return cached
    try:
        state, _created = PlatformConnectivityState.objects.get_or_create(
            key=PLATFORM_STATE_KEY,
            defaults={
                'mode': PlatformConnectivityState.MODE_UNKNOWN,
                'sync_enabled': bool(_setting('PLATFORM_AUTO_SYNC_ENABLED', True)),
            },
        )
    except (OperationalError, ProgrammingError) as exc:
        return _fallback_status(str(exc))
    status = _status_from_state(state)
    cache.set(CONNECTIVITY_CACHE_KEY, status, 30)
    return status


def probe_internet_connectivity(urls=None, timeout=None):
    if _setting('PLATFORM_FORCE_OFFLINE', False):
        return False, '', 'PLATFORM_FORCE_OFFLINE is enabled.'
    if _setting('PLATFORM_DEPLOYMENT_MODE', 'auto') == 'offline_lan':
        return False, '', 'PLATFORM_DEPLOYMENT_MODE is offline_lan.'

    check_urls = list(urls if urls is not None else _setting('PLATFORM_CONNECTIVITY_CHECK_URLS', []))
    if not check_urls:
        return False, '', 'No connectivity check URLs configured.'

    timeout_seconds = timeout if timeout is not None else _setting('PLATFORM_CONNECTIVITY_TIMEOUT_SECONDS', 3.0)
    errors = []
    for url in check_urls:
        try:
            request = Request(
                url,
                method='HEAD',
                headers={
                    'User-Agent': 'NDOH-Regulatory-Platform-Connectivity-Check/1.0',
                    'Accept': '*/*',
                },
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                status_code = response.getcode()
                if status_code < 500:
                    return True, url, ''
                errors.append(f'{url} returned HTTP {status_code}')
        except HTTPError as exc:
            if exc.code < 500:
                return True, url, f'{url} returned HTTP {exc.code}'
            errors.append(f'{url} returned HTTP {exc.code}')
        except (TimeoutError, URLError, OSError, socket.timeout) as exc:
            errors.append(f'{url}: {exc}')
    return False, '', '; '.join(errors)


def refresh_platform_connectivity(urls=None, timeout=None):
    now = timezone.now()
    try:
        state, _created = PlatformConnectivityState.objects.get_or_create(
            key=PLATFORM_STATE_KEY,
            defaults={'sync_enabled': bool(_setting('PLATFORM_AUTO_SYNC_ENABLED', True))},
        )
    except (OperationalError, ProgrammingError) as exc:
        return _fallback_status(str(exc))

    effective_forced_offline = bool(state.forced_offline or _setting('PLATFORM_FORCE_OFFLINE', False))
    if effective_forced_offline:
        state.mode = PlatformConnectivityState.MODE_OFFLINE_LAN
        state.last_checked_at = now
        state.last_offline_at = now
        state.last_error = 'Offline LAN mode is forced by settings or admin state.'
        state.consecutive_failures += 1
        state.consecutive_successes = 0
        state.save(update_fields=[
            'mode',
            'last_checked_at',
            'last_offline_at',
            'last_error',
            'consecutive_failures',
            'consecutive_successes',
            'updated_at',
        ])
        status = _status_from_state(state)
        cache.set(CONNECTIVITY_CACHE_KEY, status, 30)
        return status

    success, successful_url, error = probe_internet_connectivity(urls=urls, timeout=timeout)
    state.last_checked_at = now
    if success:
        state.mode = PlatformConnectivityState.MODE_ONLINE
        state.last_online_at = now
        state.last_successful_url = successful_url
        state.last_error = ''
        state.consecutive_successes += 1
        state.consecutive_failures = 0
    else:
        state.mode = (
            PlatformConnectivityState.MODE_OFFLINE_LAN
            if _setting('PLATFORM_OFFLINE_LAN_ENABLED', True)
            else PlatformConnectivityState.MODE_DEGRADED
        )
        state.last_offline_at = now
        state.last_error = error or 'Connectivity probe failed.'
        state.consecutive_failures += 1
        state.consecutive_successes = 0
    state.save(update_fields=[
        'mode',
        'last_checked_at',
        'last_online_at',
        'last_offline_at',
        'last_successful_url',
        'last_error',
        'consecutive_successes',
        'consecutive_failures',
        'updated_at',
    ])
    status = _status_from_state(state)
    cache.set(CONNECTIVITY_CACHE_KEY, status, 30)
    return status


def queue_sync_item(
    *,
    sync_type,
    payload,
    destination='',
    endpoint_url='',
    http_method='POST',
    headers=None,
    idempotency_key=None,
    priority=50,
    created_by=None,
    max_attempts=12,
):
    defaults = {
        'sync_type': sync_type,
        'destination': destination,
        'endpoint_url': endpoint_url,
        'http_method': http_method,
        'headers_json': headers or {},
        'payload_json': payload or {},
        'status': PlatformSyncOutboxItem.STATUS_PENDING,
        'priority': priority,
        'next_attempt_at': timezone.now(),
        'created_by': created_by,
        'max_attempts': max_attempts,
        'last_error': '',
    }
    if idempotency_key:
        item, _created = PlatformSyncOutboxItem.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults=defaults,
        )
        if item.status != PlatformSyncOutboxItem.STATUS_SYNCED:
            for key, value in defaults.items():
                setattr(item, key, value)
            item.save()
        return item
    return PlatformSyncOutboxItem.objects.create(**defaults)


def _due_sync_queryset():
    now = timezone.now()
    return PlatformSyncOutboxItem.objects.filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
        status__in=[PlatformSyncOutboxItem.STATUS_PENDING, PlatformSyncOutboxItem.STATUS_FAILED],
        attempts__lt=models_f('max_attempts'),
    ).order_by('priority', 'created_at')


def models_f(field_name):
    from django.db.models import F

    return F(field_name)


def _next_attempt_time(attempts):
    delay_minutes = min(60, 2 ** min(max(attempts, 1), 6))
    return timezone.now() + timedelta(minutes=delay_minutes)


def _dispatch_outbox_item(item):
    endpoint_url = item.endpoint_url or _setting('PLATFORM_SYNC_REMOTE_URL', '')
    if not endpoint_url:
        raise PlatformSyncError('No PLATFORM_SYNC_REMOTE_URL or item endpoint URL is configured.')

    payload = {
        'item_uuid': str(item.item_uuid),
        'sync_type': item.sync_type,
        'destination': item.destination,
        'idempotency_key': item.idempotency_key or str(item.item_uuid),
        'payload': item.payload_json or {},
        'created_at': _datetime_payload(item.created_at),
        'attempt': item.attempts,
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Idempotency-Key': item.idempotency_key or str(item.item_uuid),
    }
    if isinstance(item.headers_json, dict):
        headers.update(item.headers_json)
    api_key = _setting('PLATFORM_SYNC_API_KEY', '')
    if api_key and 'Authorization' not in headers:
        headers['Authorization'] = f'Bearer {api_key}'

    request = Request(
        endpoint_url,
        data=json.dumps(payload, ensure_ascii=True, default=str).encode('utf-8'),
        headers=headers,
        method=item.http_method,
    )
    timeout = _setting('PLATFORM_CONNECTIVITY_TIMEOUT_SECONDS', 3.0)
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.getcode()
            body = response.read(2048).decode('utf-8', errors='replace')
    except HTTPError as exc:
        body = exc.read(2048).decode('utf-8', errors='replace') if exc.fp else ''
        raise PlatformSyncError(f'HTTP {exc.code}: {body[:300]}') from exc
    except (TimeoutError, URLError, OSError, socket.timeout) as exc:
        raise PlatformSyncError(str(exc)) from exc

    if status_code < 200 or status_code >= 300:
        raise PlatformSyncError(f'HTTP {status_code}: {body[:300]}')
    return status_code, body[:1000]


def process_sync_outbox(limit=None, worker_id='platform-sync-worker', refresh_connectivity=True):
    status = refresh_platform_connectivity() if refresh_connectivity else current_platform_status(use_cache=False)
    batch_size = limit or _setting('PLATFORM_SYNC_WORKER_BATCH_SIZE', 25)
    if not status['is_online'] or not status['auto_sync_enabled']:
        return {
            'connectivity': status,
            'processed': 0,
            'synced': 0,
            'failed': 0,
            'skipped': _due_sync_queryset().count(),
            'message': 'Platform is offline/LAN-only or auto-sync is disabled.',
        }

    processed = synced = failed = 0
    for queued in list(_due_sync_queryset()[:batch_size]):
        with transaction.atomic():
            item = PlatformSyncOutboxItem.objects.select_for_update().get(pk=queued.pk)
            if not item.is_due:
                continue
            item.status = PlatformSyncOutboxItem.STATUS_IN_PROGRESS
            item.locked_at = timezone.now()
            item.locked_by = worker_id
            item.last_attempt_at = timezone.now()
            item.attempts += 1
            item.save(update_fields=[
                'status',
                'locked_at',
                'locked_by',
                'last_attempt_at',
                'attempts',
                'updated_at',
            ])

        processed += 1
        try:
            status_code, response_excerpt = _dispatch_outbox_item(item)
        except PlatformSyncError as exc:
            failed += 1
            retryable = item.attempts < item.max_attempts
            item.status = PlatformSyncOutboxItem.STATUS_FAILED if retryable else PlatformSyncOutboxItem.STATUS_BLOCKED
            item.last_error = str(exc)
            item.response_status_code = None
            item.response_body_excerpt = ''
            item.next_attempt_at = _next_attempt_time(item.attempts) if retryable else None
            item.locked_at = None
            item.locked_by = ''
            item.save(update_fields=[
                'status',
                'last_error',
                'response_status_code',
                'response_body_excerpt',
                'next_attempt_at',
                'locked_at',
                'locked_by',
                'updated_at',
            ])
            continue

        synced += 1
        item.status = PlatformSyncOutboxItem.STATUS_SYNCED
        item.last_success_at = timezone.now()
        item.last_error = ''
        item.response_status_code = status_code
        item.response_body_excerpt = response_excerpt
        item.next_attempt_at = None
        item.locked_at = None
        item.locked_by = ''
        item.save(update_fields=[
            'status',
            'last_success_at',
            'last_error',
            'response_status_code',
            'response_body_excerpt',
            'next_attempt_at',
            'locked_at',
            'locked_by',
            'updated_at',
        ])

    cache.delete(CONNECTIVITY_CACHE_KEY)
    return {
        'connectivity': current_platform_status(use_cache=False),
        'processed': processed,
        'synced': synced,
        'failed': failed,
        'skipped': max(_due_sync_queryset().count() - processed, 0),
        'message': 'Sync outbox processing completed.',
    }
