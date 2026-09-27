"""JIT scenarios for the disposable CE14 identity fixture, not a unit fake."""


def exercise(*, db, fixture, origin, prefix, initiate, complete, require, groups, configuration_dir):
    from dataclasses import asdict
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import selectors
    import signal
    from django.conf import settings
    from django.test import Client
    from seahub.auth import SESSION_KEY
    from seahub.base.accounts import User
    from seaserv import ccnet_api
    from cloudfile_extensions.jobs.store import JobStore

    checks = []
    # New process reads the same trusted configuration through Django's normal
    # app-ready validation. This private fixture file is deleted with its CA.
    config = Path(configuration_dir) / 'cf_jit_settings.py'
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('from seahub.settings import *\nENABLE_OAUTH = False\n'
            'CLOUDFILE_OIDC_ENABLED = True\nCLOUDFILE_OIDC_JIT_ENABLED = True\n')
        output.write('CLOUDFILE_POLICY_CONFIG = ' + repr(settings.CLOUDFILE_POLICY_CONFIG) + '\n')
        output.write('CLOUDFILE_OIDC_CONFIG = ' + repr(asdict(settings.CLOUDFILE_OIDC_CONFIG)) + '\n')
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'cf_jit_settings',
        'PYTHONPATH': str(configuration_dir) + ':' + ':'.join(sys.path[:4]),
        'PYTHONDONTWRITEBYTECODE': '1'}
    worker_script = os.environ.get('CF_JIT_WORKER_SCRIPT', '/scripts/cloudfile-jit-worker.py')

    def rows(sql, values=()):
        with db.cursor() as cursor:
            cursor.execute(sql, values)
            return cursor.fetchall()

    def pending(browser, token, expected):
        response = browser.get(prefix + 'pending/', secure=True, HTTP_HOST='cloudfile-smoke.invalid',
            HTTP_AUTHORIZATION='CloudFilePending ' + token)
        require(response.status_code == 200, 'pending_http_' + str(response.status_code))
        value = response.json()
        require(set(value) == {'job_id', 'status', 'retryable'} and value['status'] == expected,
                'pending_status_' + expected)
        require(not browser.session.get(SESSION_KEY), 'pending_never_authenticates')
        return value

    def queued(user_id):
        fixture.update(mode='active', claim_user=user_id, claim_sub='subject-' + user_id)
        browser = Client(enforce_csrf_checks=True)
        response = complete(browser, initiate(browser))
        require(response.status_code == 202, 'jit_callback_' + str(response.status_code))
        value = response.json()
        require(set(value) == {'job_id', 'status', 'status_token'} and value['status'] == 'pending',
                'bounded_callback')
        require(pending(browser, value['status_token'], 'queued')['job_id'] == value['job_id'], 'job_binding')
        foreign = Client().get(prefix + 'pending/', secure=True, HTTP_HOST='cloudfile-smoke.invalid',
            HTTP_AUTHORIZATION='CloudFilePending ' + value['status_token'])
        require(foreign.status_code == 401, 'pending_foreign_browser_denied')
        return browser, value

    def identity(user_id):
        users = rows('SELECT user FROM seahub_db.profile_profile WHERE login_id=%s', (user_id,))
        require(len(users) == 1, 'one_profile')
        username = users[0][0]
        accounts = rows('SELECT passwd,is_active,is_staff FROM ccnet_db.EmailUser WHERE email=%s', (username,))
        require(accounts == (('!', 1, 0),), 'active_native_no_password_or_admin')
        require(User.objects.get(email=username).username == username, 'rpc_reload_jit_user')
        require(rows('SELECT COUNT(*) FROM cf_audit_event WHERE operation=%s AND operator=%s',
            ('identity.created', user_id))[0][0] == 1, 'one_identity_created_audit')
        require(rows('SELECT COUNT(*) FROM seahub_db.social_auth_usersocialauth WHERE username=%s',
            (username,))[0][0] == 1, 'one_oidc_binding')
        return username

    def worker(job_id, status):
        result = subprocess.run([sys.executable, worker_script, '--once'],
            env=environment, capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, 'standalone_worker_exit_' + str(result.returncode))
        events = [json.loads(line) for line in result.stdout.splitlines()]
        require(events == [{'state': 'ready'}, {'state': 'job_processed', 'job_id': job_id},
            {'state': 'stopped'}], 'standalone_worker_lifecycle')
        job = JobStore(db).get(job_id)
        require(job['status'] == status, 'worker_' + status + '_' + str(job.get('error_code')))
        return job

    def authenticated(user_id, username):
        browser = Client(enforce_csrf_checks=True)
        response = complete(browser, initiate(browser))
        require(response.status_code == 302, 'fresh_oidc_login_' + str(response.status_code))
        require(browser.session.get(SESSION_KEY) == username, 'fresh_session_native_identity')
        require(browser.get('/api2/account/info/', secure=True,
            HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'authenticated_rpc_account')
        require({row[0] for row in rows('SELECT group_id FROM ccnet_db.GroupUser WHERE user_name=%s',
            (username,))} == groups, 'jit_projected_org_role')
        require({group.id for group in ccnet_api.get_groups(username)} == groups,
                'jit_rpc_projected_org_role')
        identity(user_id)

    user_id = 'jit-success'
    browser, value = queued(user_id)
    require(not rows('SELECT user FROM seahub_db.profile_profile WHERE login_id=%s', (user_id,)),
            'request_does_not_create_identity')
    checks.append('jit_pending_browser_proof')
    worker(value['job_id'], 'succeeded')
    username = identity(user_id)
    pending(browser, value['status_token'], 'succeeded')
    status = browser.get('/api2/account/info/', secure=True,
        HTTP_HOST='cloudfile-smoke.invalid').status_code
    require(status in {401, 403}, 'worker_no_browser_session_status_' + str(status))
    checks.append('jit_native_worker_and_projection')
    authenticated(user_id, username)
    authenticated(user_id, username)
    require(rows('SELECT COUNT(*) FROM cf_background_job WHERE actor=%s AND kind=%s',
        (user_id, 'identity.provision'))[0][0] == 1, 'one_success_job')
    checks.append('jit_fresh_login_and_reuse')

    user_id = 'jit-recovery'
    fixture['fail_fetch'] = 2  # HTTPS failure after the identity transaction commits.
    browser, value = queued(user_id)
    failure = worker(value['job_id'], 'failed')
    require(failure['error_code'] == 'UPSTREAM_UNAVAILABLE' and failure['attempts'] == 1
        and fixture['calls_by_user'][user_id] == 2, 'actual_second_https_fetch_failure')
    username = identity(user_id)
    require(pending(browser, value['status_token'], 'failed')['retryable'], 'failed_retryable')
    checks.append('jit_failure_after_identity_commit')
    fixture.pop('fail_fetch')
    retry_browser, retry = queued(user_id)  # Fresh verified OIDC requeues the same job.
    require(retry['job_id'] == value['job_id'], 'retry_same_job')
    recovered = worker(retry['job_id'], 'succeeded')
    require(recovered['attempts'] == 2 and recovered['error_code'] is None,
            'recovered_attempt_and_error_clear')
    require(identity(user_id) == username, 'recovery_same_native_user')
    pending(retry_browser, retry['status_token'], 'succeeded')
    authenticated(user_id, username)
    checks.append('jit_resume_without_duplicate_identity')

    user_id = 'jit-disabled'
    browser, value = queued(user_id)
    fixture['mode'] = 'disabled'
    failure = worker(value['job_id'], 'failed')
    require(failure['error_code'] == 'SUBJECT_DISABLED', 'disabled_directory_failure_code')
    require(not rows('SELECT user FROM seahub_db.profile_profile WHERE login_id=%s', (user_id,)),
            'disabled_never_created')
    pending(browser, value['status_token'], 'failed')
    checks.append('jit_disabled_subject_not_created')
    # An idle standalone worker also drains its owned connection/Redis host.
    result = subprocess.run([sys.executable, worker_script, '--once'],
        env=environment, capture_output=True, text=True, timeout=30)
    require(result.returncode == 0 and [json.loads(line) for line in result.stdout.splitlines()] ==
        [{'state': 'ready'}, {'state': 'stopped'}], 'standalone_idle_shutdown')
    checks.append('jit_standalone_process_lifecycle')
    process = subprocess.Popen([sys.executable, worker_script], env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            require(bool(selector.select(timeout=15)), 'idle_worker_ready_deadline')
            require(json.loads(process.stdout.readline()) == {'state': 'ready'}, 'idle_worker_ready')
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
        require(process.returncode == 0 and [json.loads(line) for line in stdout.splitlines()] ==
            [{'state': 'stopped'}], 'idle_worker_signal_shutdown')
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    checks.append('jit_sigterm_shutdown')
    # Explicit disablement rejects before claiming any queued job.
    with config.open('a') as output:
        output.write('CLOUDFILE_OIDC_JIT_ENABLED = False\n')
    result = subprocess.run([sys.executable, worker_script, '--once'],
        env=environment, capture_output=True, text=True, timeout=30)
    require(result.returncode == 1 and not result.stdout.strip(), 'disabled_worker_never_ready')
    checks.append('jit_disabled_process_refused')
    return checks
