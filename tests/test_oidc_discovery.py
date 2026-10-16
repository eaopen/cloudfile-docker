import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('oidc_discover', Path(__file__).parents[1] / 'tools/oidc-discover.py')
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.metadata = dict(issuer='https://idp.example/application/o/files/',
            response_types_supported=['code'], id_token_signing_alg_values_supported=['RS256'],
            code_challenge_methods_supported=['S256'], authorization_endpoint='https://idp.example/authorize',
            token_endpoint='https://idp.example/token', userinfo_endpoint='https://idp.example/userinfo',
            jwks_uri='https://idp.example/jwks')
        self.args = dict(issuer=self.metadata['issuer'], client_id='files', client_secret='fixture-only',
            redirect_uri='https://files.example/api/v2.1/cloudfile/extensions/identity/v1/callback/')

    def test_metadata_generates_existing_config_contract(self):
        value = discovery.configuration(self.metadata, **self.args)
        self.assertEqual(value['token_url'], self.metadata['token_endpoint'])
        self.assertEqual(value['issuer'], self.args['issuer'])
        self.assertEqual(value['user_id_claim'], 'userId')

    def test_mismatched_issuer_and_unsupported_protocol_fail(self):
        for field, value in [('issuer', 'https://other.example/'), ('issuer', self.args['issuer'].rstrip('/')),
                             ('id_token_signing_alg_values_supported', ['HS256']),
                             ('response_types_supported', ['token']),
                             ('response_types_supported', 'code'),
                             ('token_endpoint_auth_methods_supported', ['private_key_jwt']),
                             ('code_challenge_methods_supported', ['plain'])]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                discovery.configuration(dict(self.metadata, **{field:value}), **self.args)

    def test_endpoint_credentials_fragments_and_unsafe_schemes_rejected(self):
        for endpoint in ('file:///tmp/keys', 'https://user:secret@idp.example/token',
                         'https://idp.example/token#fragment', 'https://idp.example/\ntoken', None):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                discovery.configuration(dict(self.metadata, token_endpoint=endpoint), **self.args)

    def test_identity_claim_cannot_silently_merge_accounts(self):
        for claim in ('email', 'sub', 'preferred_username', ''):
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                discovery.configuration(self.metadata, **self.args, user_id_claim=claim)

    def test_duplicate_metadata_and_redirects_are_rejected(self):
        with self.assertRaises(ValueError):
            discovery.unique_object([('issuer','one'),('issuer','two')])
        self.assertIsNone(discovery.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))
