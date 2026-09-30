"""Disposable real Meili/native/SQL/OIDC search acceptance, never a fake ACL."""
import base64
import json
import tempfile
import time
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


def exercise(*, db, user, manager, initiate, complete, require, configuration_dir):
    from django.conf import settings
    from django.test import Client
    from seaserv import seafile_api
    from cloudfile_extensions.authorization import gunicorn
    checks = []
    browser = Client(enforce_csrf_checks=True)
    browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(complete(browser, initiate(browser)).status_code == 302, 'search_oidc_login')
    repo = seafile_api.create_repo('Disposable resource search', 'fixture', manager.username)
    seafile_api.share_repo(repo, manager.username, user.username, 'rw')
    with tempfile.NamedTemporaryFile() as file:
        file.write(b'not fulltext indexed'); file.flush()
        seafile_api.post_file(repo, file.name, '/', 'drawing.prt', manager.username)
        seafile_api.post_file(repo, file.name, '/', 'plain.txt', manager.username)
    # Enroll only this fixture's new library in the real native managed guard.
    with db.cursor() as sql:
        sql.execute('INSERT INTO cf_managed_library(repo_id,created_at) VALUES(%s,UTC_TIMESTAMP(6))', (repo,))
    subject = base64.urlsafe_b64encode(b'fixture-user-1').decode().rstrip('=')
    def post(path, body, key=None, **overrides):
        headers = dict(HTTP_HOST='cloudfile-smoke.invalid', HTTP_ORIGIN='https://cloudfile-smoke.invalid',
            HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value,
            HTTP_X_CLOUDFILE_EXPECTED_SUBJECT=subject)
        if key is not None: headers['HTTP_IDEMPOTENCY_KEY'] = key
        headers.update(overrides)
        return browser.post('/api/v2.1/cloudfile/extensions/' + path, data=json.dumps(body),
            content_type='application/json', secure=True, **headers)
    def ok(response, status=200):
        require(response.status_code == status, 'search_http_' + str(response.status_code) + '_' + json.loads(response.content).get('code', 'unknown'))
        return json.loads(response.content)
    ref = dict(repo_id=repo, path='/drawing.prt', kind='file')
    initial = ok(post('annotations/v1/resources/resolve/', ref))
    saved = ok(post('annotations/v1/resources/', dict(resource=ref, expected_revision=initial['revision'],
        changes=dict(description='fixturegear')), 'search-description'), 201)
    query = dict(q='fixturegear', repo_id=repo)
    require(post('search/v1/query/', query).status_code == 503, 'search_unpublished_closed')
    host = gunicorn._host.deployment.search_host
    config = Path(configuration_dir) / 'cf_search_settings.py'
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('from seahub.settings import *\nENABLE_OAUTH = False\n')
        for name, value in dict(CLOUDFILE_OIDC_ENABLED=True, CLOUDFILE_AUTHORIZATION_ENABLED=True,
                CLOUDFILE_RESOURCE_SEARCH_ENABLED=True, CLOUDFILE_ANNOTATIONS_ENABLED=True,
                CLOUDFILE_POLICY_CONFIG=settings.CLOUDFILE_POLICY_CONFIG,
                CLOUDFILE_OIDC_CONFIG=asdict(settings.CLOUDFILE_OIDC_CONFIG),
                CLOUDFILE_RESOURCE_SECRET=settings.CLOUDFILE_RESOURCE_SECRET,
                CLOUDFILE_RESOURCE_SEARCH_CONFIG=settings.CLOUDFILE_RESOURCE_SEARCH_CONFIG).items():
            output.write(name + ' = ' + repr(value) + '\n')
        output.write('def CLOUDFILE_RESOURCE_LIFECYCLE_READER(cursor, reference):\n'
            '    from seaserv import seafile_api\n'
            '    from cloudfile_extensions.resources.native import NativeResourceReader\n'
            '    return NativeResourceReader(seafile_api)(cursor, reference)\n')
    environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'cf_search_settings',
        'PYTHONPATH': str(configuration_dir) + ':' + ':'.join(sys.path[:4]), 'PYTHONDONTWRITEBYTECODE': '1'}
    deadline = time.monotonic() + 30
    while True:
        worker = subprocess.run([sys.executable, '/scripts/cloudfile-search-worker.py', 'initialize', '--once'],
            env=environment, capture_output=True, text=True, timeout=20)
        require(worker.returncode == 0, 'search_standalone_initialization')
        state = json.loads(worker.stdout.strip())['state']
        if state == 'initialized': break
        require(state == 'pending' and time.monotonic() < deadline, 'search_initialization_deadline')
        time.sleep(.1)
    checks.append('standalone_search_worker_initializes_durable_tasks_and_captures_global_snapshot')
    worker = subprocess.run([sys.executable, '/scripts/cloudfile-search-worker.py', 'rebuild',
        '--repo-id', repo, '--poll-seconds', '1'], env=environment, capture_output=True, text=True, timeout=35)
    diagnostic = next((line.removeprefix('CF_SEARCH_WORKER_DIAGNOSTIC=') for line in worker.stderr.splitlines()
        if line.startswith('CF_SEARCH_WORKER_DIAGNOSTIC=')), '')
    require(worker.returncode == 0 and json.loads(worker.stdout.strip().splitlines()[-1])['state'] == 'published',
        'search_standalone_rebuild_and_publication_' + diagnostic)
    checks.append('standalone_search_worker_enumerates_native_snapshot_and_publishes_after_catchup')
    trace = []
    def diagnostic(frame, event, argument):
        if event == 'exception' and '/cloudfile_extensions/search/' in frame.f_code.co_filename:
            name = argument[0].__name__
            if name not in {'StopIteration', 'GeneratorExit'}:
                trace.append(frame.f_code.co_filename.rsplit('/', 1)[-1] + ':' + str(frame.f_lineno) + ':' + name)
        return diagnostic
    sys.settrace(diagnostic)
    try:
        response = post('search/v1/query/', query)
    finally:
        sys.settrace(None)
    if response.status_code == 503:
        require(False, 'search_trace_' + '_'.join(trace[-12:]))
    result = ok(response)
    require([item['reference'] for item in result['items']] == [ref] and 'total' not in result and
        result['provider'] == 'meilisearch' and result['fallback'] is False, 'search_description_result')
    require(ok(post('search/v1/query/', dict(q='plain', repo_id=repo)))['items'][0]['annotation']['uid'] is None,
        'search_unannotated_native_resource')
    checks.append('native_full_snapshot_initialization_publication_name_description_and_sparse_search')
    require(post('search/v1/query/', query, HTTP_X_CLOUDFILE_EXPECTED_SUBJECT=
        base64.urlsafe_b64encode(b'wrong-subject').decode().rstrip('=')).status_code == 403, 'search_subject_mismatch')
    require(post('search/v1/query/', query, HTTP_X_CSRFTOKEN='').status_code == 403, 'search_csrf')
    # Advance actual outbox plans and actual asynchronous Meili task receipts.
    ok(post('annotations/v1/resources/', dict(resource=ref, expected_revision=saved['revision'],
        changes=dict(description='fixturebolt')), 'search-description-update'))
    with host.consumer('search-fixture').open() as consumer:
        deadline = time.monotonic() + 20
        while True:
            state = consumer.run_once()
            if state in {'recovery_required', 'retry'}:
                with db.cursor() as sql:
                    sql.execute("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.action')),search_error FROM cf_event_outbox WHERE search_state IN ('recovery','queued') AND search_error IS NOT NULL ORDER BY sequence LIMIT 1")
                    failed = sql.fetchone()
                require(False, 'search_incremental_' + state + '_' + '_'.join(str(value) for value in failed or ()))
            if state == 'idle':
                with db.cursor() as sql:
                    sql.execute("SELECT COUNT(*) FROM cf_event_outbox WHERE search_state<>'done'")
                    remaining = sql.fetchone()[0]
                if remaining == 0: break
            require(time.monotonic() < deadline, 'search_consumer_deadline')
            time.sleep(.15)
    require(ok(post('search/v1/query/', dict(q='fixturebolt', repo_id=repo)))['items'][0]['reference'] == ref,
        'search_incremental_description')
    checks.append('durable_attribute_event_projection_and_meili_task_confirmation')
    current = ok(post('annotations/v1/resources/resolve/', ref))
    tagged = ok(post('annotations/v1/resources/user-tag-values/', dict(reference=ref,
        revision=current['revision'], values=[dict(label='fixturetag')]), 'search-bind-tag'))
    tag_id = tagged['tags'][0]['tag_id']
    with host.consumer('search-fixture-tag').open() as consumer:
        deadline = time.monotonic() + 20
        while True:
            state = consumer.run_once()
            require(state not in {'recovery_required', 'retry'}, 'search_tag_incremental_' + state)
            if state == 'idle':
                with db.cursor() as sql:
                    sql.execute("SELECT COUNT(*) FROM cf_event_outbox WHERE search_state<>'done'")
                    remaining = sql.fetchone()[0]
                if remaining == 0: break
            require(time.monotonic() < deadline, 'search_tag_consumer_deadline')
            time.sleep(.15)
    require([item['reference'] for item in ok(post('search/v1/query/', dict(q='fixturetag', repo_id=repo, tag_ids=[tag_id])))['items']] == [ref],
        'search_tag_name_and_id_filter')
    ok(post('annotations/v1/resources/user-tag-values/', dict(reference=ref,
        revision=tagged['revision'], values=[]), 'search-unbind-tag'))
    require(ok(post('search/v1/query/', dict(q='fixturetag', repo_id=repo, tag_ids=[tag_id])))['items'] == [],
        'search_removed_tag_filtered_before_consumer_runs')
    checks.append('tag_binding_outbox_projection_and_current_tag_filter_after_unbind')
    seafile_api.remove_share(repo, manager.username, user.username)
    require(ok(post('search/v1/query/', dict(q='fixturebolt', repo_id=repo)))['items'] == [],
        'search_real_native_share_revocation')
    seafile_api.share_repo(repo, manager.username, user.username, 'rw')
    checks.append('indexed_candidate_filtered_after_actual_ce_share_revocation')
    # Account disablement is the supported native identity revocation boundary.
    user.is_active = False; user.save()
    require(post('search/v1/query/', query).status_code in {401, 403, 503}, 'search_disabled_native_account')
    user.is_active = True; user.save()
    browser = Client(enforce_csrf_checks=True)
    browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(complete(browser, initiate(browser)).status_code == 302, 'search_relogin_after_reactivation')
    checks.append('subject_csrf_and_current_native_account_rejections')
    # A changed native head cannot reuse the published scan. This is a SQL
    # boundary fault fixture, not evidence of an implemented byte-event bridge.
    with db.cursor() as sql:
        sql.execute("UPDATE cf_search_rebuild SET commit_id=%s WHERE generation=%s AND repo_id=%s",
            ('0' * 40, settings.CLOUDFILE_RESOURCE_SEARCH_CONFIG['generation'], repo))
    require(post('search/v1/query/', query).status_code == 503, 'search_snapshot_mismatch_closed')
    checks.append('mismatched_native_snapshot_never_returns_stale_search_success')
    return checks
