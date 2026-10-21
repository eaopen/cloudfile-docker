#!/usr/bin/env python3
"""Render the small, idempotent CloudFile v0.2 Seahub settings block."""

import json
import os
import pprint
import re
from urllib.parse import urlparse


BEGIN_MARKER = "# BEGIN CLOUDFILE V0.2"
END_MARKER = "# END CLOUDFILE V0.2"
URLCONF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
EXTENSION_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
PUBLIC_CAPABILITY_FIELDS = {"enabled", "version", "provider"}
RESERVED_DOMAINS = {
    "directory", "authorization", "library-policy", "directory-acl", "annotations",
    "audit", "search", "locks", "local-edit", "migration", "transfer", "identity",
}


def _extension_apps(raw_value):
    result = []
    for item in raw_value.split(","):
        module = item.strip()
        if not module:
            continue
        if not URLCONF_RE.fullmatch(module):
            raise ValueError(f"invalid CLOUDFILE_EXTENSION_APPS entry: {module!r}")
        result.append(module)
    return result


def _extension_urlconfs(raw_value):
    if not raw_value:
        return {}
    value = json.loads(raw_value)
    if not isinstance(value, dict):
        raise ValueError("CLOUDFILE_EXTENSION_URLCONFS_JSON must contain a JSON object")
    for name, module in value.items():
        if not isinstance(name, str) or not EXTENSION_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid CloudFile extension name: {name!r}")
        if name in RESERVED_DOMAINS:
            raise ValueError("deployment extension cannot replace a core CloudFile domain")
        if not isinstance(module, str) or not URLCONF_RE.fullmatch(module):
            raise ValueError(f"invalid CloudFile extension URLConf: {module!r}")
    return value


def _capabilities(raw_value):
    if not raw_value:
        return {}
    value = json.loads(raw_value)
    if not isinstance(value, dict):
        raise ValueError("CLOUDFILE_CAPABILITIES_JSON must contain a JSON object")
    for name, capability in value.items():
        if not isinstance(name, str) or not CAPABILITY_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid CloudFile capability name: {name!r}")
        if isinstance(capability, bool):
            continue
        if not isinstance(capability, dict):
            raise ValueError(f"capability {name!r} must be a boolean or object")
        unknown_fields = set(capability) - PUBLIC_CAPABILITY_FIELDS
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"capability {name!r} has unsupported public fields: {fields}")
        if not isinstance(capability.get("enabled", False), bool):
            raise ValueError(f"capability {name!r} enabled must be a boolean")
        for field in ("version", "provider"):
            if field in capability and not isinstance(capability[field], str):
                raise ValueError(f"capability {name!r} {field} must be a string")
    return value


def _strict_config(raw_value, name):
    if not raw_value:
        return None

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate {name} field")
            value[key] = item
        return value

    def invalid_constant(_):
        raise ValueError(f"{name} must contain strict JSON")

    try:
        value = json.loads(raw_value, object_pairs_hook=pairs,
            parse_constant=invalid_constant)
    except (TypeError, json.JSONDecodeError):
        raise ValueError(f"{name} must contain strict JSON") from None
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value






def _boolean(environment, name, default=False):
    raw_value = environment.get(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false")


def _authentik_settings(environment):
    if not _boolean(environment, "CLOUDFILE_AUTHENTIK_ENABLED"):
        return {}

    required = (
        "CLOUDFILE_AUTHENTIK_URL",
        "CLOUDFILE_AUTHENTIK_CLIENT_ID",
        "CLOUDFILE_AUTHENTIK_CLIENT_SECRET",
    )
    missing = [name for name in required if not environment.get(name, "").strip()]
    if missing:
        raise ValueError(f"missing Authentik settings: {', '.join(missing)}")

    base_url = environment["CLOUDFILE_AUTHENTIK_URL"].strip().rstrip("/")
    parsed = urlparse(base_url)
    allow_insecure = _boolean(environment, "CLOUDFILE_AUTHENTIK_ALLOW_INSECURE")
    if parsed.scheme not in (("http", "https") if allow_insecure else ("https",)) or not parsed.netloc:
        raise ValueError("CLOUDFILE_AUTHENTIK_URL must be an absolute HTTPS URL")

    redirect_url = environment.get("CLOUDFILE_AUTHENTIK_REDIRECT_URL", "").strip()
    # Same protocol resolution as bootstrap.get_proto(): an unset
    # SEAFILE_SERVER_PROTOCOL means HTTP unless the deployment terminates TLS
    # itself. Defaulting to HTTPS here made the generated OAuth redirect claim a
    # scheme the deployment does not serve, and the Hub then marked
    # sessionid/csrftoken Secure on an HTTP entry.
    protocol = environment.get("SEAFILE_SERVER_PROTOCOL", "").strip().lower()
    if protocol not in ("http", "https"):
        protocol = ("https" if environment.get(
            "SEAFILE_SERVER_LETSENCRYPT", "false").strip().lower() == "true" else "http")
    if not redirect_url:
        hostname = environment.get("SEAFILE_SERVER_HOSTNAME", "").strip().rstrip("/")
        if not hostname:
            raise ValueError(
                "set CLOUDFILE_AUTHENTIK_REDIRECT_URL or SEAFILE_SERVER_PROTOCOL and "
                "SEAFILE_SERVER_HOSTNAME"
            )
        redirect_url = f"{protocol}://{hostname}/oauth/callback/"

    redirect = urlparse(redirect_url)
    # The redirect is the deployment's own public entry, whose scheme it already
    # declares through SEAFILE_SERVER_PROTOCOL (or an explicit redirect URL).
    # Forcing HTTPS here would refuse to start an HTTP deployment that the
    # product supports; CLOUDFILE_AUTHENTIK_ALLOW_INSECURE keeps governing the
    # IdP-facing URLs, which are a different trust boundary.
    allowed_redirect = ("http", "https") if (allow_insecure or protocol == "http") else ("https",)
    if redirect.scheme not in allowed_redirect or not redirect.netloc:
        raise ValueError("Authentik redirect URL must be an absolute HTTP/HTTPS URL "
                         "matching the deployment protocol")

    return {
        "ENABLE_OAUTH": True,
        "OAUTH_PROVIDER": "authentik-oauth",
        "OAUTH_CLIENT_ID": environment["CLOUDFILE_AUTHENTIK_CLIENT_ID"].strip(),
        "OAUTH_CLIENT_SECRET": environment["CLOUDFILE_AUTHENTIK_CLIENT_SECRET"],
        "OAUTH_REDIRECT_URL": redirect_url,
        "OAUTH_AUTHORIZATION_URL": f"{base_url}/application/o/authorize/",
        "OAUTH_TOKEN_URL": f"{base_url}/application/o/token/",
        "OAUTH_USER_INFO_URL": f"{base_url}/application/o/userinfo/",
        "OAUTH_SCOPE": ["openid", "profile", "email"],
        "OAUTH_ATTRIBUTE_MAP": {
            "sub": (True, "uid"),
            "email": (False, "contact_email"),
            "name": (False, "name"),
            "preferred_username": (False, "login_id"),
        },
        "OAUTH_CREATE_UNKNOWN_USER": _boolean(
            environment, "CLOUDFILE_AUTHENTIK_CREATE_UNKNOWN_USER", False
        ),
        "OAUTH_ACTIVATE_USER_AFTER_CREATION": _boolean(
            environment, "CLOUDFILE_AUTHENTIK_ACTIVATE_USER_AFTER_CREATION", False
        ),
        "DISABLE_SSO_USER_LOCAL_PWD_LOGIN": _boolean(
            environment, "CLOUDFILE_AUTHENTIK_DISABLE_LOCAL_PASSWORD", True
        ),
        "OAUTH_ENABLE_INSECURE_TRANSPORT": allow_insecure,
    }


RETIRED_POLICY_SETTINGS = ('CLOUDFILE_POLICY_CONFIG_JSON', 'CLOUDFILE_POLICY_WORKER_HOOKS', 'CLOUDFILE_AUTHORIZATION_ENABLED', 'CLOUDFILE_ADMIN_POLICY_ENABLED', 'CLOUDFILE_DIRECTORY_AUTHORIZATION', 'CLOUDFILE_OIDC_ENABLED', 'CLOUDFILE_OIDC_CONFIG_JSON', 'CLOUDFILE_OIDC_JIT_ENABLED', 'CLOUDFILE_OIDC_BACKCHANNEL_ENABLED', 'CLOUDFILE_TRANSFER_ENABLED', 'CLOUDFILE_EDITING_ENABLED', 'CLOUDFILE_LOCAL_EDIT_ENABLED', 'CLOUDFILE_LOCAL_EDIT_INSTANCE', 'CLOUDFILE_AGENT2_OPTIMISTIC_UPLOAD_ENABLED', 'CLOUDFILE_AGENT2_EXCLUSIVE_ENABLED', 'CLOUDFILE_RESOURCE_SECRET', 'CLOUDFILE_RESOURCE_SEARCH_ENABLED', 'CLOUDFILE_ANNOTATIONS_ENABLED', 'CLOUDFILE_AUDIT_QUERY_ENABLED', 'CLOUDFILE_AUDIT_EXPORT_ENABLED', 'CLOUDFILE_AUDIT_CURSOR_SECRET', 'CLOUDFILE_AUDIT_RESULT_ROOT')

def render_settings(environment=None):
    environment = os.environ if environment is None else environment
    requested = [name for name in RETIRED_POLICY_SETTINGS
                 if str(environment.get(name, '')).strip().lower() not in ('', 'false', '0')]
    if requested:
        raise ValueError('Retired policy settings are unsupported: ' + ', '.join(requested))
    extension_apps = _extension_apps(environment.get("CLOUDFILE_EXTENSION_APPS", ""))
    urlconfs = _extension_urlconfs(environment.get("CLOUDFILE_EXTENSION_URLCONFS_JSON", ""))
    capabilities = _capabilities(environment.get("CLOUDFILE_CAPABILITIES_JSON", ""))
    authentik = _authentik_settings(environment)
    capabilities.setdefault("auth.basic", {"enabled": True, "version": "14"})
    capabilities.setdefault("protocol.webdav", {
        "enabled": _boolean(environment, "CLOUDFILE_WEBDAV_ENABLED", False), "version": "14"})
    capabilities.setdefault("auth.oidc", {"enabled": False, "version": "1", "provider": "authentik"})
    lines = [
        BEGIN_MARKER,
        f"EXTRA_INSTALLED_APPS = list(dict.fromkeys(globals().get('EXTRA_INSTALLED_APPS', []) + {pprint.pformat(['cloudfile_extensions', *extension_apps], sort_dicts=True)}))",
        "SITE_ROOT_URLCONF = 'cloudfile_extensions.root_urls'",
        "EXTRA_MIDDLEWARE = ['cloudfile_extensions.permission_middleware.CloudFilePermissionMiddleware']",
        f"CLOUDFILE_EXTENSION_URLCONFS = {pprint.pformat(urlconfs, sort_dicts=True)}",
        f"CLOUDFILE_CAPABILITIES = {pprint.pformat(capabilities, sort_dicts=True)}",
        f"CF_SSO_GROUP_OWNER = {environment.get('CF_SSO_GROUP_OWNER', '')!r}",
        f"CF_SSO_MAX_REMOVAL_RATIO = {environment.get('CF_SSO_MAX_REMOVAL_RATIO', '0.5')!r}",
        f"CLOUDFILE_WEBDAV_SERVICE_ENABLED = {_boolean(environment, 'CLOUDFILE_WEBDAV_ENABLED', False)!r}",
        f"CF_NATIVE_DATABASE_NAME = {environment.get('SEAFILE_MYSQL_DB_CCNET_DB_NAME', 'ccnet_db')!r}",
    ]
    lines.extend(f"{name} = {pprint.pformat(value, sort_dicts=True)}" for name, value in authentik.items())
    lines.extend((END_MARKER, ""))
    return "\n".join(lines)


def write_settings(path, environment=None):
    block = render_settings(environment)
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            current = settings_file.read()
    except FileNotFoundError:
        current = ""

    begin = current.find(BEGIN_MARKER)
    end = current.find(END_MARKER)
    if begin >= 0 or end >= 0:
        if begin < 0 or end < begin:
            raise ValueError(f"invalid CloudFile settings markers in {path}")
        end += len(END_MARKER)
        if end < len(current) and current[end] == "\n":
            end += 1
        retained = current[:begin] + current[end:]
        updated = retained.rstrip() + "\n\n" + block
    else:
        updated = (current.rstrip() + "\n\n" if current.strip() else "") + block

    if updated == current:
        return False

    with open(path, "w", encoding="utf-8") as settings_file:
        settings_file.write(updated)
    return True


def write_policy_worker_hooks(path, environment=None, *, v2=False):
    """Remove the retired owned block; never install a policy worker."""
    environment = os.environ if environment is None else environment
    begin_marker = "# BEGIN CLOUDFILE POLICY WORKER HOOKS"
    end_marker = "# END CLOUDFILE POLICY WORKER HOOKS"
    try:
        with open(path, "r", encoding="utf-8") as source:
            current = source.read()
    except FileNotFoundError:
        current = ""
    begin, end = current.find(begin_marker), current.find(end_marker)
    if begin >= 0 or end >= 0:
        if (begin < 0 or end < begin or current.count(begin_marker) != 1 or
                current.count(end_marker) != 1):
            raise ValueError("invalid policy worker hook markers")
        end += len(end_marker)
        if current[end:end + 1] == "\n":
            end += 1
        base = current[:begin] + current[end:]
    else:
        base = current
    updated = base
    if updated == current:
        return False
    with open(path, "w", encoding="utf-8") as target:
        target.write(updated)
    return True
