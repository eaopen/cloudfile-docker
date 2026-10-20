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
            if key.startswith(('OAUTH_', 'CF_DIRECTORY_')) or key in names:
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
