"""One canonical Seahub root with CloudFile-owned native compatibility aliases."""
import ast
from urllib.parse import urlsplit


def read_settings(filename, names):
    """Read selected native literals without executing deployment Python."""
    if not filename.is_file():
        return {}
    result = {}
    for node in ast.parse(filename.read_text()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                isinstance(node.targets[0], ast.Name)):
            key = node.targets[0].id
            if key.startswith('OAUTH_') or key in names:
                result[key] = ast.literal_eval(node.value)
    return result


def web_settings(public_url, previous, *, existing):
    origin = urlsplit(public_url)
    if (origin.scheme not in ('http', 'https') or not origin.hostname or
            origin.path not in ('', '/') or origin.query or origin.fragment or
            origin.username or origin.password):
        raise ValueError('public URL must be an HTTP(S) origin')
    public_url = public_url.rstrip('/')
    root = previous.get('SITE_ROOT', '/seafile/') if existing else '/cfile/'
    if root not in ('/cfile/', '/seafile/'):
        raise ValueError('unsupported canonical SITE_ROOT')
    file_path = ('/seafhttp' if existing else '/cfhttp')
    if existing and previous.get('FILE_SERVER_ROOT'):
        file_path = urlsplit(previous['FILE_SERVER_ROOT']).path.rstrip('/')
        if file_path not in ('/cfhttp', '/seafhttp'):
            raise ValueError('unsupported file server path')
    return {
        'SITE_ROOT': root,
        'SERVICE_URL': public_url + root.rstrip('/'),
        'FILE_SERVER_ROOT': public_url + file_path,
        'MEDIA_URL': root + 'media/',
        'STATIC_URL': root + 'media/assets/',
        # Both ingress paths must receive the same native session/CSRF cookies.
        'SESSION_COOKIE_PATH': '/',
        'CSRF_COOKIE_PATH': '/',
    }


def nginx_config(template, root):
    if root not in ('/cfile/', '/seafile/'):
        raise ValueError('unsupported canonical SITE_ROOT')
    if '__CF_CANONICAL__' not in template:
        raise ValueError('canonical nginx template marker missing')
    return template.replace('__CF_CANONICAL__', root)


def checkout_enabled(configured, legacy=None, *, existing, guard_installed=False):
    """Checkout is enabled by default on new V2, or whenever valid Guard exists.

    The environment setting is a deployment capability, never a runtime lock
    bypass. Existing installations must not silently alter their schemas.
    """
    def parse(raw):
        if raw is None:
            return None
        if not isinstance(raw, str) or raw.lower() not in ('true', 'false', '1', '0'):
            raise ValueError('Checkout setting must be true or false')
        return raw.lower() in ('true', '1')

    requested, previous = parse(configured), parse(legacy)
    if requested is not None and previous is not None and requested != previous:
        raise ValueError('Conflicting Checkout capability settings')
    if requested is None:
        requested = previous
    if not existing:
        # Fresh V2 installs the single Guard table unless explicitly unsupported.
        return requested is not False
    if guard_installed:
        # Disabling the enforcement for any installed Guard may bypass an
        # existing Checkout. A deliberate schema retirement is a separate task.
        if requested is False:
            raise ValueError('Cannot disable Checkout while a Guard table is installed')
        return True
    if requested is True:
        raise ValueError('Existing instance has no V2 Guard table; use an approved migration')
    return False


def native_guard_config(source, enabled):
    """Adjust only the native Guard capability key in a copied seafile.conf.

    Preserve all unrelated CE14 settings and their original case/format.
    Never rewrite the existing volume's original configuration.
    """
    if type(enabled) is not bool:
        raise ValueError('invalid native Guard availability')
    lines = source.splitlines(keepends=True)
    sections = [i for i, line in enumerate(lines) if line.strip() == '[cloudfile]']
    if len(sections) > 1:
        raise ValueError('duplicate [cloudfile] sections')
    desired = 'v2_edit_enabled=' + ('true' if enabled else 'false') + '\n'
    if not sections:
        separator = '' if not source or source.endswith(('\n', '\r')) else '\n'
        return source + separator + '[cloudfile]\n' + desired
    begin = sections[0] + 1
    end = next((i for i in range(begin, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    matches = [i for i in range(begin, end)
               if lines[i].lstrip().startswith('v2_edit_enabled')
               and lines[i].lstrip()[len('v2_edit_enabled'):].lstrip().startswith('=')]
    if len(matches) > 1:
        raise ValueError('duplicate native Guard setting')
    if matches:
        lines[matches[0]] = desired
    else:
        lines.insert(end, desired)
    return ''.join(lines)
