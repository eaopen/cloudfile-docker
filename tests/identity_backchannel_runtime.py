"""Hosted signed notification/fences and a separate native session deletion process."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import secrets
import sys
import time
from urllib.parse import urlencode


def exercise(*, db, fixture, prefix, initiate, complete, require, configuration_dir, claims, notification):
    from django.conf import settings
    from django.contrib.sessions.models import Session
    from django.test import Client
    from cloudfile_extensions.identity.native_session import LOGOUT_HINT_KEY
    from cloudfile_extensions.jobs.store import JobStore

    checks = []
    config = Path(configuration_dir) / 'cf_logout_settings.py'
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('from seahub.settings import *\nENABLE_OAUTH = False\n'
            'CLOUDFILE_OIDC_ENABLED = True\nCLOUDFILE_OIDC_BACKCHANNEL_ENABLED = True\n')
        output.write('CLOUDFILE_POLICY_CONFIG = ' + repr(settings.CLOUDFILE_POLICY_CONFIG) + '\n')
        output.write('CLOUDFILE_OIDC_CONFIG = ' + repr(asdict(settings.CLOUDFILE_OIDC_CONFIG)) + '\n')
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'cf_logout_settings',
        'PYTHONPATH': str(configuration_dir) + ':' + ':'.join(sys.path[:4]), 'PYTHONDONTWRITEBYTECODE': '1'}

    def rows(sql, values=()):
        with db.cursor() as cursor:
            cursor.execute(sql, values)
            return cursor.fetchall()

    def login():
        browser = Client(enforce_csrf_checks=True)
        response = complete(browser, initiate(browser))
        require(response.status_code == 302, 'backchannel_login_' + str(response.status_code))
        return browser, browser.session.session_key, claims(browser.session[LOGOUT_HINT_KEY]['id_token'])

    def post(token, **headers):
        # Fresh client: no implicit browser cookie or CSRF token is allowed.
        return Client(enforce_csrf_checks=True).post(prefix + 'logout/backchannel/',
            data=urlencode({'logout_token': token}), content_type='application/x-www-form-urlencoded',
            secure=True, HTTP_HOST='cloudfile-smoke.invalid', **headers)

    def run_worker(expected_job):
        result = subprocess.run([sys.executable, '/scripts/cloudfile-logout-worker.py', '--once'],
            env=environment, capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, 'logout_process_exit_' + str(result.returncode))
        events = [json.loads(line) for line in result.stdout.splitlines()]
        require(events == [{'state': 'ready'}, {'state': 'job_processed', 'job_id': expected_job},
            {'state': 'stopped'}], 'logout_process_lifecycle')
        require(JobStore(db).get(expected_job)['status'] == 'succeeded', 'logout_job_succeeded')

    # One real IdP sid can own multiple application sessions. Use one to prove
    # immediate request fencing and another untouched row to prove worker deletion.
    fixture['session_sid'] = secrets.token_urlsafe(16)
    first, first_key, first_claims = login()
    same_sid, same_sid_key, same_sid_claims = login()
    require(same_sid_claims['sid'] == first_claims['sid'] and same_sid_key != first_key, 'shared_idp_sid')
    fixture.pop('session_sid')
    second, second_key, second_claims = login()
    target = {'sub': first_claims['sub'], 'sid': first_claims['sid']}
    require(post(notification({**target, 'aud': 'wrong-audience'})).status_code == 401, 'wrong_aud_denied')
    require(post(notification({**target, 'nonce': 'forbidden'})).status_code == 401, 'logout_nonce_denied')
    require(post(first.session[LOGOUT_HINT_KEY]['id_token']).status_code == 401, 'id_token_not_logout_token')
    token = notification(target)
    require(post(token, HTTP_COOKIE='language=en').status_code == 400, 'notification_cookie_denied')
    require(post(token, HTTP_AUTHORIZATION='Bearer alternate').status_code == 400, 'alternate_auth_denied')
    require(not rows('SELECT job_id FROM cf_background_job WHERE kind=%s', ('identity.logout',)),
            'invalid_notifications_never_queued')
    checks.append('backchannel_signature_purpose_and_cookie_boundary')

    directory_calls = fixture['directory_calls']
    fixture['mode'] = 'outage'
    response = post(token)
    require(response.status_code == 200 and response.content == b'', 'signed_cookie_free_ack')
    require(fixture['directory_calls'] == directory_calls, 'intake_independent_of_employee_directory')
    jobs = rows('SELECT job_id FROM cf_background_job WHERE kind=%s', ('identity.logout',))
    require(len(jobs) == 1 and JobStore(db).get(jobs[0][0])['status'] == 'queued', 'durable_ack_not_execution')
    require(Session.objects.filter(session_key=first_key).exists(), 'ack_before_async_delete')
    require(post(token).status_code == 200 and len(rows(
        'SELECT job_id FROM cf_background_job WHERE kind=%s', ('identity.logout',))) == 1, 'notification_idempotent_replay')
    require(first.get('/api2/account/info/', secure=True,
        HTTP_HOST='cloudfile-smoke.invalid').status_code in {401, 403}, 'sid_fence_before_worker')
    require(Session.objects.filter(session_key=same_sid_key).exists(), 'untouched_sid_row_before_worker')
    checks.append('backchannel_durable_fence_and_replay')
    run_worker(jobs[0][0])
    require(not Session.objects.filter(session_key=first_key).exists() and not rows(
        'SELECT session_key FROM cf_oidc_session WHERE session_key=%s', (first_key,)), 'sid_native_delete_and_index')
    require(not Session.objects.filter(session_key=same_sid_key).exists() and not rows(
        'SELECT session_key FROM cf_oidc_session WHERE session_key=%s', (same_sid_key,)), 'worker_actually_deleted_native_row')
    require(Session.objects.filter(session_key=second_key).exists() and second.get('/api2/account/info/',
        secure=True, HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'other_sid_preserved')
    checks.append('backchannel_standalone_sid_deletion')

    # Sub notification drains older sessions, while a later fresh login survives.
    sub_token = notification({'sub': second_claims['sub']})
    require(post(sub_token).status_code == 200, 'subject_ack')
    second_job = rows('SELECT job_id FROM cf_background_job WHERE kind=%s AND status=%s',
        ('identity.logout', 'queued'))
    require(len(second_job) == 1, 'subject_job')
    fixture['mode'] = 'active'
    time.sleep(1.05)  # Actual new ID Token iat exceeds accepted notification cutoff.
    fresh, fresh_key, fresh_claims = login()
    require(fresh_claims['iat'] > second_claims['iat'], 'fresh_authentication_after_cutoff')
    run_worker(second_job[0][0])
    require(not Session.objects.filter(session_key=second_key).exists() and not rows(
        'SELECT session_key FROM cf_oidc_session WHERE session_key=%s', (second_key,)), 'subject_native_delete')
    require(Session.objects.filter(session_key=fresh_key).exists() and fresh.get('/api2/account/info/',
        secure=True, HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'late_worker_preserves_fresh_login')
    checks.append('backchannel_subject_cutoff_and_later_login')
    with config.open('a') as output:
        output.write('CLOUDFILE_OIDC_BACKCHANNEL_ENABLED = False\n')
    result = subprocess.run([sys.executable, '/scripts/cloudfile-logout-worker.py', '--once'],
        env=environment, capture_output=True, text=True, timeout=30)
    require(result.returncode == 1 and not result.stdout.strip(), 'disabled_logout_worker_refused')
    checks.append('backchannel_disabled_worker_refused')
    return checks
