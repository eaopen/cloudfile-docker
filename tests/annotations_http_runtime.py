"""Actual OIDC session, C metadata authorization, native history and HTTP saves."""
import base64
import json
import tempfile


def exercise(*, db, user, manager, initiate, complete, require):
    from django.conf import settings
    from django.test import Client
    from seaserv import seafile_api
    checks = []
    browser = Client(enforce_csrf_checks=True)
    browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(complete(browser, initiate(browser)).status_code == 302, 'annotations_oidc_login')
    with db.cursor() as cursor:
        cursor.execute('SELECT repo_id FROM RepoOwner WHERE owner_id=%s', (manager.username,))
        repos = cursor.fetchall()
    require(len(repos) == 1, 'annotations_fixture_library')
    repo = repos[0][0]
    # Native personal share is the actual qualification for the eTech user,
    # not a mocked authority or an administrator session.
    seafile_api.share_repo(repo, manager.username, user.username, 'rw')
    with tempfile.NamedTemporaryFile() as temporary:
        temporary.write(b'annotation fixture'); temporary.flush()
        seafile_api.post_file(repo, temporary.name, '/', 'drawing.prt', manager.username)
    capabilities = browser.get('/api/v2.1/cloudfile/capabilities/', secure=True,
        HTTP_HOST='cloudfile-smoke.invalid')
    require(capabilities.status_code == 200, 'annotations_capabilities_status')
    values = json.loads(capabilities.content)['capabilities']
    require(all(values[name]['enabled'] is True for name in
        ('resource.description', 'resource.local-open-type', 'tag.extended')), 'annotations_capabilities_ready')
    require(all(values[name]['enabled'] is False for name in
        ('local.open-edit', 'search.resources', 'file.lock')), 'annotations_unrelated_capabilities_closed')
    checks.append('live_worker_publishes_only_ready_annotation_capabilities')
    reference = dict(repo_id=repo, path='/drawing.prt', kind='file')
    prefix = '/api/v2.1/cloudfile/extensions/annotations/v1/'
    subject = base64.urlsafe_b64encode(b'fixture-user-1').decode().rstrip('=')
    def post(route, body, key=None, **overrides):
        headers = dict(HTTP_HOST='cloudfile-smoke.invalid', HTTP_ORIGIN='https://cloudfile-smoke.invalid',
            HTTP_X_CSRFTOKEN=browser.cookies[settings.CSRF_COOKIE_NAME].value,
            HTTP_X_CLOUDFILE_EXPECTED_SUBJECT=subject)
        if key: headers['HTTP_IDEMPOTENCY_KEY'] = key
        headers.update(overrides)
        return browser.post(prefix + route, data=json.dumps(body), content_type='application/json', secure=True, **headers)
    def ok(response, status=200):
        require(response.status_code == status, 'annotations_http_status_' + str(response.status_code))
        return json.loads(response.content)
    initial = ok(post('resources/resolve/', reference))
    require(initial['uid'] is None and initial['access']['write'] is True, 'annotations_sparse_shared_read')
    body = dict(resource=reference, expected_revision=initial['revision'],
        changes=dict(description='eTech drawing', local_open_type='UG12'))
    saved = ok(post('resources/', body, 'attributes-1'), 201)
    require(ok(post('resources/', body, 'attributes-1'), 201) == saved, 'annotations_durable_replay')
    checks.append('authenticated_description_open_type_write_and_replay')
    labels = dict(reference=reference, revision=saved['revision'], values=[dict(label='drawing')])
    tagged = ok(post('resources/user-tag-values/', labels, 'tags-1'))
    current = ok(post('resources/resolve/', reference))
    require(current['description'] == 'eTech drawing' and current['local_open_type'] == 'UG12'
        and current['tags'][0]['label'] == 'drawing' and current['revision'] == tagged['revision'], 'annotations_readback')
    batch = ok(post('batch/', dict(references=[reference])))
    require(batch['items'][0]['snapshot'] == current, 'annotations_batch_readback')
    checks.append('authenticated_user_tag_save_and_single_batch_readback')
    require(post('resources/', body, 'stale-1').status_code == 409, 'annotations_stale_condition')
    require(post('resources/resolve/', reference, HTTP_X_CLOUDFILE_EXPECTED_SUBJECT=
        base64.urlsafe_b64encode(b'other-user').decode().rstrip('=')).status_code == 403, 'annotations_subject_mismatch')
    require(post('resources/', body, 'csrf-1', HTTP_X_CSRFTOKEN='').status_code == 403, 'annotations_csrf')
    checks.append('stale_revision_subject_mismatch_and_csrf_rejected')
    import time
    from uuid import uuid4
    import jwt
    credential = settings.CLOUDFILE_SYSTEM_TAG_PROVIDER_CREDENTIALS['tags-v1']
    now = int(time.time())
    provider_token = 'Bearer ' + jwt.encode(dict(iss='etech-tags', aud='cloudfile-tags', sub='etech-tags',
        iat=now, exp=now + 60, jti=str(uuid4()), scope='tags.system.write'), credential.secret,
        algorithm='HS256', headers={'kid': 'tags-v1'})
    provider_body = dict(reference=reference, revision=current['revision'],
        updates=[dict(namespace='etech:project', values=[dict(code='P1', label='Project 1')])])
    provider_headers = dict(HTTP_X_CLOUDFILE_PROVIDER_AUTHORIZATION=provider_token)
    require(post('resources/system-tags/', provider_body, 'provider-missing').status_code == 401, 'provider_credential_required')
    system = ok(post('resources/system-tags/', provider_body, 'provider-1', **provider_headers))
    require({tag['label'] for tag in system['tags']} == {'Project 1', 'drawing'}, 'provider_preserves_user_tags')
    require(ok(post('resources/system-tags/', provider_body, 'provider-1', **provider_headers)) == system, 'provider_replay')
    provider_body['revision'] = system['revision']
    provider_body['updates'][0]['namespace'] = 'foreign:project'
    require(post('resources/system-tags/', provider_body, 'provider-foreign', **provider_headers).status_code == 403, 'provider_foreign_namespace')
    provider_body['updates'][0] = dict(namespace='etech:project', values=[])
    cleared = ok(post('resources/system-tags/', provider_body, 'provider-clear', **provider_headers))
    require([tag['label'] for tag in cleared['tags']] == ['drawing'], 'provider_clear_preserves_user_tags')
    checks.append('provider_machine_scope_namespace_save_replay_and_clear')
    # Downgrade the actual CE share, then remove it. Each request reloads the
    # same-cursor qualification; capability discovery never grants permission.
    seafile_api.set_share_permission(repo, manager.username, user.username, 'r')
    readonly = ok(post('resources/resolve/', reference))
    require(readonly['access']['read'] is True and readonly['access']['write'] is False, 'annotations_readonly_access')
    body['expected_revision'] = readonly['revision']; body['changes']['description'] = 'must not save'
    require(post('resources/', body, 'readonly-1').status_code == 403, 'annotations_readonly_write_denied')
    provider_body['revision'] = readonly['revision']
    require(post('resources/system-tags/', provider_body, 'provider-readonly', **provider_headers).status_code == 403, 'provider_readonly_write_denied')
    seafile_api.remove_share(repo, manager.username, user.username)
    require(post('resources/resolve/', reference).status_code == 403, 'annotations_revoked_read_denied')
    checks.append('native_readonly_and_revoked_share_enforced')
    return checks
