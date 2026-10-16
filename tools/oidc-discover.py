#!/usr/bin/env python3
"""Generate explicit CloudFile OIDC config from a trusted issuer's metadata.

Discovery runs during deployment preparation, never in a login request. No
client credential is sent to Discovery, and redirects are not followed.
"""
import argparse
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener


def endpoint(value):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        raise ValueError('invalid OIDC endpoint')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment):
        raise ValueError('invalid OIDC endpoint')
    return value


def unique_object(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('duplicate Discovery field')
        value[key] = item
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def discover(issuer, *, ca_bundle=None):
    endpoint(issuer)
    if urlsplit(issuer).query:
        raise ValueError('issuer must not have a query')
    context = ssl.create_default_context(cafile=ca_bundle)
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    with opener.open(issuer.rstrip('/') + '/.well-known/openid-configuration', timeout=10) as response:
        if response.status != 200:
            raise ValueError('Discovery did not return HTTP 200')
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Discovery document exceeds size limit')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON constant')))


def configuration(metadata, *, issuer, client_id, client_secret, redirect_uri,
                  user_id_claim='userId', ca_bundle=None):
    endpoint(issuer)
    endpoint(redirect_uri)
    if not isinstance(metadata, dict) or metadata.get('issuer') != issuer:
        raise ValueError('Discovery issuer does not exactly match configured issuer')
    for field, required in [('response_types_supported', 'code'),
                            ('id_token_signing_alg_values_supported', 'RS256')]:
        supported = metadata.get(field)
        if not isinstance(supported, list) or required not in supported:
            raise ValueError('Discovery does not support the required code/RS256 flow')
    methods = metadata.get('code_challenge_methods_supported')
    if methods is not None and (not isinstance(methods, list) or 'S256' not in methods):
        raise ValueError('Discovery does not support PKCE S256')
    authentication = metadata.get('token_endpoint_auth_methods_supported', ['client_secret_basic'])
    if not isinstance(authentication, list) or 'client_secret_basic' not in authentication:
        raise ValueError('Discovery does not support the configured client authentication method')
    if not client_id or not client_secret or not user_id_claim:
        raise ValueError('client and stable directory UID claim are required')
    # The directory UID is a business identity, not a globally unique OIDC sub.
    if user_id_claim in ('sub', 'email', 'preferred_username'):
        raise ValueError('use a stable directory UID claim or explicit account prebinding')
    result = dict(issuer=issuer, client_id=client_id, client_secret=client_secret,
                  redirect_uri=redirect_uri, user_id_claim=user_id_claim)
    for target, source in [('authorization_url', 'authorization_endpoint'),
                           ('token_url', 'token_endpoint'), ('userinfo_url', 'userinfo_endpoint'),
                           ('jwks_url', 'jwks_uri')]:
        result[target] = endpoint(metadata.get(source))
    if ca_bundle:
        result['ca_bundle'] = ca_bundle
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issuer', required=True)
    parser.add_argument('--client-id', required=True)
    parser.add_argument('--redirect-uri', required=True)
    parser.add_argument('--user-id-claim', default='userId')
    parser.add_argument('--client-secret-env', default='CLOUDFILE_OIDC_CLIENT_SECRET')
    parser.add_argument('--ca-bundle')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = configuration(discover(args.issuer, ca_bundle=args.ca_bundle),
            issuer=args.issuer, client_id=args.client_id,
            client_secret=os.environ.get(args.client_secret_env, ''),
            redirect_uri=args.redirect_uri, user_id_claim=args.user_id_claim, ca_bundle=args.ca_bundle)
        # Never emit a client secret to terminal output or create a public file.
        with tempfile.NamedTemporaryFile(mode='w', dir=args.output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, indent=2)
            stream.write('\n')
        try:
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
        print('OIDC configuration written; mode 0600. Review endpoints before deployment.')
    except Exception:
        parser.exit(1, 'OIDC Discovery/configuration failed; verify issuer, metadata, UID claim and credentials.\n')


if __name__ == '__main__':
    main()
