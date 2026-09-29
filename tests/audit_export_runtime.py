"""Disposable OIDC audit export through HTTP, an independent worker and native reauthorization."""
import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID


def exercise(*, db, user, initiate, complete, require, configuration_dir):
    from django.conf import settings
    from django.test import Client
    from seaserv import seafile_api
    from cloudfile_extensions.jobs.store import JobStore

    checks = []
    browser = Client(enforce_csrf_checks=True)
    browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(complete(browser, initiate(browser)).status_code == 302, 'audit_oidc_login')
    # Actual CE ownership and C root policy, rather than an injected authorization callback.
    repo = seafile_api.create_repo('Disposable audit', 'runtime export fixture', user.username)
    require(str(UUID(repo)) == repo, 'audit_native_repo')
    prefix = '/api/v2.1/cloudfile/extensions/audit/v1/exports/'
    subject = base64.urlsafe_b64encode(b'fixture-user-1').decode().rstrip('=')
    headers = dict(secure=True, HTTP_HOST='cloudfile-smoke.invalid',
        HTTP_X_CLOUDFILE_EXPECTED_SUBJECT=subject)
    now = datetime.now(timezone.utc)
    request = dict(repo_id=repo,
        start=(now - timedelta(days=1)).isoformat().replace('+00:00', 'Z'),
        end=(now + timedelta(days=1)).isoformat().replace('+00:00', 'Z'))
    response = browser.post(prefix, data=json.dumps(request), content_type='application/json',
        HTTP_ORIGIN='https://cloudfile-smoke.invalid',
        HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value,
        HTTP_IDEMPOTENCY_KEY='audit-runtime-1', **headers)
    require(response.status_code == 202, 'audit_submit_' + str(response.status_code))
    submitted = json.loads(response.content)
    job_id = submitted['job_id']
    require(str(UUID(job_id)) == job_id and submitted['repo_id'] == repo and
        submitted['status'] == 'queued', 'audit_submit_durable')
    require(JobStore(db).get(job_id)['status'] == 'queued', 'audit_job_stored')
    checks.append('authenticated_native_owner_creates_durable_export')

    # A separate process must normalize OIDC settings before opening PolicyHost.
    config = Path(configuration_dir) / 'cf_audit_settings.py'
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('from seahub.settings import *\nENABLE_OAUTH = False\n')
        for name, value in dict(CLOUDFILE_OIDC_ENABLED=True,
                CLOUDFILE_AUTHORIZATION_ENABLED=True, CLOUDFILE_AUDIT_QUERY_ENABLED=True,
                CLOUDFILE_AUDIT_EXPORT_ENABLED=True,
                CLOUDFILE_POLICY_CONFIG=settings.CLOUDFILE_POLICY_CONFIG,
                CLOUDFILE_OIDC_CONFIG=asdict(settings.CLOUDFILE_OIDC_CONFIG),
                CLOUDFILE_AUDIT_CURSOR_SECRET=settings.CLOUDFILE_AUDIT_CURSOR_SECRET,
                CLOUDFILE_AUDIT_RESULT_ROOT=settings.CLOUDFILE_AUDIT_RESULT_ROOT).items():
            output.write(name + ' = ' + repr(value) + '\n')
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'cf_audit_settings',
        'PYTHONPATH': str(configuration_dir) + ':' + ':'.join(sys.path[:4]),
        'PYTHONDONTWRITEBYTECODE': '1'}
    worker = subprocess.run([sys.executable, os.environ['CF_AUDIT_WORKER_SCRIPT'], '--once'],
        env=environment, capture_output=True, text=True, timeout=45)
    diagnostic = next((line.removeprefix('CF_AUDIT_WORKER_DIAGNOSTIC=')
        for line in worker.stderr.splitlines() if line.startswith('CF_AUDIT_WORKER_DIAGNOSTIC=')), '')
    require(worker.returncode == 0, 'audit_worker_exit_' + str(worker.returncode) +
        (';worker=' + diagnostic if diagnostic else ''))
    require(JobStore(db).get(job_id)['status'] == 'succeeded', 'audit_worker_completed')
    checks.append('standalone_worker_writes_private_result')

    status = browser.get(prefix + job_id + '/', **headers)
    require(status.status_code == 200, 'audit_status')
    metadata = json.loads(status.content)
    require(metadata['status'] == 'succeeded' and metadata['result_url'] ==
        prefix + job_id + '/result/', 'audit_result_location')
    downloaded = browser.get(metadata['result_url'], **headers)
    require(downloaded.status_code == 200 and downloaded['Content-Type'].startswith('text/csv') and
        downloaded.content.startswith(b'"id","event_id"'), 'audit_result_delivery')
    with db.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM cf_audit_event WHERE operation=%s AND repo_id=%s AND result=%s',
            ('audit.export.download', repo, 'attempted'))
        require(cursor.fetchone()[0] == 1, 'audit_download_attempt_fact')
    checks.append('result_reauthorized_and_attempt_recorded')

    user.is_active = False
    user.save()
    denied = browser.get(metadata['result_url'], **headers)
    require(denied.status_code in {401, 403, 503}, 'audit_disabled_owner_denied')
    checks.append('native_disabled_owner_cannot_redownload')

    # The same packaged worker must eventually remove an expired result, not
    # just deny its HTTP URL. This disposable job is the only row changed.
    job = JobStore(db).get(job_id)
    artifact = Path(settings.CLOUDFILE_AUDIT_RESULT_ROOT) / (job_id + '.' + str(job['lease_epoch']) + '.csv')
    require(artifact.is_file(), 'audit_result_exists_before_expiry')
    checkpoint = dict(job['checkpoint'], expires_at=(now - timedelta(seconds=1)).timestamp())
    with db.cursor() as cursor:
        cursor.execute('UPDATE cf_background_job SET checkpoint=%s WHERE job_id=%s AND status=%s',
            (json.dumps(checkpoint, sort_keys=True), job_id, 'succeeded'))
        require(cursor.rowcount == 1, 'audit_expiry_fixture_updated')
    cleanup = subprocess.run([sys.executable, os.environ['CF_AUDIT_WORKER_SCRIPT'], '--once'],
        env=environment, capture_output=True, text=True, timeout=45)
    require(cleanup.returncode == 0 and not artifact.exists(), 'audit_expired_result_removed')
    require(JobStore(db).get(job_id)['status'] == 'succeeded', 'audit_job_facts_retained')
    checks.append('expired_private_csv_removed_without_deleting_job')
    return checks
