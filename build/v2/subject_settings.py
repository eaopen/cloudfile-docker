"""Render the V2 identity/ACL deployment contract without executing settings."""
import configparser

NAMES = frozenset({
    'CF_DIRECTORY_URL', 'CF_DIRECTORY_TOKEN', 'CF_DIRECTORY_SECRET',
    'CF_DIRECTORY_KEY_ID', 'CF_DIRECTORY_ISSUER', 'CF_DIRECTORY_AUDIENCE',
    'CF_DIRECTORY_SERVICE_ID', 'CF_DIRECTORY_PROVIDER', 'CF_SUBJECT_TTL',
    'CF_DIRECTORY_TIMEOUT', 'CF_ACL_PROVIDER', 'CF_ACL_SUBJECT_ENSURE',
    'CF_ACL_CACHE_TTL', 'CF_V2_ACL_ENABLED',
})


def subject_settings(previous, environ):
    values = {key: previous[key] for key in NAMES if key in previous}
    values.update({key: environ[key] for key in NAMES if key in environ})
    for key, lower, upper in (('CF_SUBJECT_TTL', 30, 1800),
                              ('CF_DIRECTORY_TIMEOUT', 1, 30),
                              ('CF_ACL_CACHE_TTL', 0, 300)):
        if key in values:
            value = values[key]
            if isinstance(value, str) and value.isascii() and value.isdecimal():
                value = int(value)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('invalid ' + key)
            values[key] = value
    enabled = values.get('CF_V2_ACL_ENABLED', False)
    if isinstance(enabled, str) and enabled.lower() in ('true', 'false'):
        enabled = enabled.lower() == 'true'
    if type(enabled) is not bool:
        raise ValueError('invalid CF_V2_ACL_ENABLED')
    values['CF_V2_ACL_ENABLED'] = enabled
    if values.get('CF_DIRECTORY_TOKEN'):
        raise ValueError('static Directory bearer tokens are not supported')
    credentials = ('SECRET', 'KEY_ID', 'ISSUER', 'AUDIENCE', 'SERVICE_ID')
    configured = bool(values.get('CF_DIRECTORY_URL')) or any(values.get('CF_DIRECTORY_' + k) for k in credentials)
    if enabled and not configured:
        raise ValueError('ACL requires Directory machine credentials')
    if configured:
        for key in ('CF_DIRECTORY_URL', *('CF_DIRECTORY_' + k for k in credentials)):
            if not isinstance(values.get(key), str) or not values[key].strip():
                raise ValueError('incomplete Directory machine credentials')
        if len(values['CF_DIRECTORY_SECRET'].encode('utf-8')) < 32:
            raise ValueError('invalid Directory machine credential')
        provider = values.get('CF_DIRECTORY_PROVIDER') or 'etech'
        values['CF_DIRECTORY_PROVIDER'] = provider
        if values.get('CF_ACL_PROVIDER', provider) != provider:
            raise ValueError('ACL and Directory providers must match')
        values['CF_ACL_PROVIDER'] = provider
        # This deployment assembles A+B; it must not accidentally wire A's
        # incompatible positional signature or an arbitrary bypass callback.
        adapter = 'cloudfile_ext.v2.runtime.ensure_acl_subject'
        if values.get('CF_ACL_SUBJECT_ENSURE', adapter) != adapter:
            raise ValueError('invalid ACL subject adapter')
        values['CF_ACL_SUBJECT_ENSURE'] = adapter
    return values


def native_acl_config(content, enabled):
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(content)
    if not config.has_section('cloudfile'):
        config.add_section('cloudfile')
    config.set('cloudfile', 'v2_acl_enabled', 'true' if enabled else 'false')
    from io import StringIO
    output = StringIO()
    config.write(output)
    return output.getvalue()
