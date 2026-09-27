"""Real native sessions and RP protocol transport in the disposable identity fixture."""
from html.parser import HTMLParser
import secrets
import time
from urllib.parse import urlsplit


class LogoutForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = self.method = None
        self.fields = {}
        self.forms = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'form':
            self.forms += 1
            self.action, self.method = values.get('action'), values.get('method')
        elif tag == 'input':
            name = values.get('name')
            if name in self.fields:
                raise ValueError('duplicate logout form input')
            self.fields[name] = values.get('value')


def exercise(*, db, fixture, origin, prefix, initiate, complete, require, ca_bundle):
    from django.conf import settings
    from django.contrib.sessions.models import Session
    from django.test import Client
    import requests
    from seahub.auth import SESSION_KEY
    from cloudfile_extensions.identity.native_session import LOGOUT_HINT_KEY
    from cloudfile_extensions.identity.logout_state import LOGOUT_COOKIE

    checks = []

    def indexed(key):
        with db.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM cf_oidc_session WHERE session_key=%s', (key,))
            return cursor.fetchone()[0] == 1

    def expire(browser, response):
        for name, cookie in response.cookies.items():
            if str(cookie['max-age']) == '0' and name in browser.cookies:
                del browser.cookies[name]

    def login(browser=None):
        browser = browser or Client(enforce_csrf_checks=True)
        browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
        response = complete(browser, initiate(browser))
        require(response.status_code == 302, 'rp_login_' + str(response.status_code))
        require(browser.session.get(SESSION_KEY), 'rp_authenticated_session')
        require(LOGOUT_HINT_KEY in browser.session, 'verified_hint_server_side')
        require(indexed(browser.session.session_key), 'rp_session_indexed')
        return browser

    def post_logout(browser, *, csrf=True):
        headers = {'HTTP_ORIGIN': 'https://cloudfile-smoke.invalid'}
        if csrf:
            headers['HTTP_X_CSRFTOKEN'] = browser.cookies[settings.CSRF_COOKIE_NAME].value
        response = browser.post(prefix + 'logout/idp/', data='',
            content_type='application/octet-stream', secure=True,
            HTTP_HOST='cloudfile-smoke.invalid', **headers)
        expire(browser, response)
        return response

    def carrier(browser):
        old_key = browser.session.session_key
        hint = browser.session[LOGOUT_HINT_KEY]['id_token']
        response = post_logout(browser)
        require(response.status_code == 200 and 'Location' not in response, 'rp_post_form_response')
        require(not Session.objects.filter(session_key=old_key).exists() and not indexed(old_key),
                'rp_native_session_and_index_deleted')
        form = LogoutForm()
        form.feed(response.content.decode())
        require(form.forms == 1 and form.method == 'post' and form.action == origin + '/logout',
                'fixed_https_logout_form')
        require(set(form.fields) == {'id_token_hint', 'post_logout_redirect_uri', 'state'}
            and form.fields['id_token_hint'] == hint, 'verified_hint_only_in_post_body')
        require(response["Content-Security-Policy"].startswith("default-src 'none';")
            and 'form-action ' + origin + ';' in response['Content-Security-Policy'], 'rp_csp_origin')
        require(response.cookies[LOGOUT_COOKIE]['secure'] and response.cookies[LOGOUT_COOKIE]['httponly']
            and response.cookies[LOGOUT_COOKIE]['samesite'] == 'Lax', 'rp_browser_cookie')
        return form, old_key

    def provider(form):
        with requests.Session() as transport:
            transport.trust_env = False
            return transport.post(form.action, data=form.fields, verify=ca_bundle,
                                  allow_redirects=False, timeout=10)

    browser = login()
    preserved_key = browser.session.session_key
    require(post_logout(browser, csrf=False).status_code == 403, 'rp_csrf_required')
    require(Session.objects.filter(session_key=preserved_key).exists() and indexed(preserved_key),
            'csrf_rejection_preserves_session')
    checks.append('rp_csrf_and_server_hint')
    other = login()
    other_key = other.session.session_key
    form, old_key = carrier(browser)
    require(Session.objects.filter(session_key=other_key).exists() and indexed(other_key),
            'rp_local_logout_only_current_session')
    require(other.get('/api2/account/info/', secure=True,
        HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'other_session_still_usable')
    response = provider(form)
    require(response.status_code == 302 and fixture['rp_requests'] == 1, 'rp_https_provider_post')
    returned = urlsplit(response.headers['Location'])
    require(returned.scheme == 'https' and returned.netloc == 'cloudfile-smoke.invalid', 'fixed_return_origin')
    return_path = returned.path + '?' + returned.query
    require('id_token_hint' not in returned.query, 'hint_not_in_return_url')
    checks.append('rp_local_delete_and_https_post')

    attacker = Client(enforce_csrf_checks=True)
    attacker.cookies[LOGOUT_COOKIE] = secrets.token_urlsafe(32)
    require(attacker.get(return_path, secure=True, HTTP_HOST='cloudfile-smoke.invalid').status_code == 401,
            'rp_return_wrong_browser_denied')
    binding = browser.cookies[LOGOUT_COOKIE].value
    time.sleep(1.05)  # Fresh actual IdP iat exceeds the native logout cutoff.
    login(browser)
    new_key = browser.session.session_key
    require(new_key != old_key, 'intervening_login_new_session')
    response = browser.get(return_path, secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(response.status_code == 200 and response.json() == {'rp_returned': True, 'idp_logged_out': None},
            'rp_return_correlation_only')
    expire(browser, response)
    require(Session.objects.filter(session_key=new_key).exists() and indexed(new_key)
        and browser.get('/api2/account/info/', secure=True,
            HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'return_preserves_intervening_login')
    browser.cookies[LOGOUT_COOKIE] = binding
    require(browser.get(return_path, secure=True, HTTP_HOST='cloudfile-smoke.invalid').status_code == 401,
            'rp_consumed_state_replay_denied')
    checks.append('rp_browser_state_and_delayed_return')

    # The local session is already terminated before handing off to the IdP.
    browser.cookies.pop(LOGOUT_COOKIE, None)
    form, failed_key = carrier(browser)
    fixture['rp_mode'] = 'outage'
    require(provider(form).status_code == 503 and fixture['rp_requests'] == 2, 'rp_real_provider_outage')
    require(not Session.objects.filter(session_key=failed_key).exists() and not indexed(failed_key),
            'idp_outage_does_not_restore_local_session')
    require(browser.get('/api2/account/info/', secure=True,
        HTTP_HOST='cloudfile-smoke.invalid').status_code in {401, 403}, 'idp_outage_local_access_denied')
    checks.append('rp_idp_failure_keeps_local_session_deleted')
    return checks
