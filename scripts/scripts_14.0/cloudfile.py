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


def _policy_config(raw_value):
    return _strict_config(raw_value, "CLOUDFILE_POLICY_CONFIG_JSON")


def _oidc_config(raw_value):
    value = _strict_config(raw_value, "CLOUDFILE_OIDC_CONFIG_JSON")
    if value is None:
        return None
    required = {"issuer", "client_id", "client_secret", "redirect_uri",
                "authorization_url", "token_url", "userinfo_url", "jwks_url"}
    optional = {"user_id_claim", "ca_bundle", "end_session_url", "post_logout_redirect_uri"}
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError("OIDC configuration has missing or unsupported fields")
    if any(not isinstance(value[name], str) or not value[name] or "\x00" in value[name]
           for name in required):
        raise ValueError("OIDC configuration requires non-empty strings")
    for name in ("issuer", "redirect_uri", "authorization_url", "token_url", "userinfo_url", "jwks_url",
                 "end_session_url", "post_logout_redirect_uri"):
        if value.get(name) is None:
            continue
        url = value[name]
        if not isinstance(url, str) or any(ord(char) < 33 for char in url):
            raise ValueError("OIDC endpoints require trusted HTTPS URLs")
        try:
            parsed = urlparse(url)
            valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                     and not parsed.password and not parsed.fragment)
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("OIDC endpoints require trusted HTTPS URLs")
    if (value.get("end_session_url") is None) != (value.get("post_logout_redirect_uri") is None):
        raise ValueError("OIDC logout endpoint and return URI must be configured together")
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
    if not redirect_url:
        protocol = environment.get("SEAFILE_SERVER_PROTOCOL", "https").strip().lower()
        hostname = environment.get("SEAFILE_SERVER_HOSTNAME", "").strip().rstrip("/")
        if protocol not in ("http", "https") or not hostname:
            raise ValueError(
                "set CLOUDFILE_AUTHENTIK_REDIRECT_URL or SEAFILE_SERVER_PROTOCOL and "
                "SEAFILE_SERVER_HOSTNAME"
            )
        redirect_url = f"{protocol}://{hostname}/oauth/callback/"

    redirect = urlparse(redirect_url)
    if redirect.scheme not in (("http", "https") if allow_insecure else ("https",)) or not redirect.netloc:
        raise ValueError("Authentik redirect URL must be an absolute HTTPS URL")

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


def render_settings(environment=None):
    environment = os.environ if environment is None else environment
    extension_apps = _extension_apps(environment.get("CLOUDFILE_EXTENSION_APPS", ""))
    urlconfs = _extension_urlconfs(environment.get("CLOUDFILE_EXTENSION_URLCONFS_JSON", ""))
    capabilities = _capabilities(environment.get("CLOUDFILE_CAPABILITIES_JSON", ""))
    policy_config = _policy_config(environment.get("CLOUDFILE_POLICY_CONFIG_JSON", ""))
    oidc_config = _oidc_config(environment.get("CLOUDFILE_OIDC_CONFIG_JSON", ""))
    oidc_enabled = _boolean(environment, "CLOUDFILE_OIDC_ENABLED", False)
    oidc_jit_enabled = _boolean(environment, "CLOUDFILE_OIDC_JIT_ENABLED", False)
    authentik = _authentik_settings(environment)
    if oidc_enabled and (oidc_config is None or policy_config is None
            or not _boolean(environment, "CLOUDFILE_POLICY_WORKER_HOOKS", False)):
        raise ValueError("enabled OIDC requires OIDC config, policy config and worker hooks")
    if oidc_enabled and authentik:
        raise ValueError("CloudFile OIDC and the legacy Authentik OAuth preset cannot both be enabled")
    if oidc_jit_enabled and not oidc_enabled:
        raise ValueError("OIDC JIT requires the explicit OIDC host")
    capabilities.setdefault("auth.basic", {"enabled": True, "version": "14"})
    webdav_enabled = _boolean(environment, "CLOUDFILE_WEBDAV_ENABLED", False)
    authorization_enabled = _boolean(environment, "CLOUDFILE_AUTHORIZATION_ENABLED", False)
    local_edit_enabled = _boolean(environment, "CLOUDFILE_LOCAL_EDIT_ENABLED", False)
    transfer_enabled = _boolean(environment, "CLOUDFILE_TRANSFER_ENABLED", False)
    if (authorization_enabled or transfer_enabled) and (policy_config is None
            or not _boolean(environment, "CLOUDFILE_POLICY_WORKER_HOOKS", False)):
        raise ValueError("enabled authorization or transfer requires policy config and worker hooks")
    if transfer_enabled and not _boolean(environment, "ENABLE_GO_FILESERVER", False):
        raise ValueError("enabled CloudFile transfer requires ENABLE_GO_FILESERVER=true")
    capabilities.setdefault(
        "protocol.webdav",
        {"enabled": webdav_enabled, "version": "14"},
    )
    capabilities.setdefault(
        "auth.oidc",
        {"enabled": False, "version": "1", "provider": "authentik"},
    )

    lines = [
        BEGIN_MARKER,
        f"EXTRA_INSTALLED_APPS = {pprint.pformat(['cloudfile_extensions', *extension_apps], sort_dicts=True)}",
        "SITE_ROOT_URLCONF = 'cloudfile_extensions.root_urls'",
        f"CLOUDFILE_EXTENSION_URLCONFS = {pprint.pformat(urlconfs, sort_dicts=True)}",
        f"CLOUDFILE_CAPABILITIES = {pprint.pformat(capabilities, sort_dicts=True)}",
        f"CLOUDFILE_POLICY_CONFIG = {pprint.pformat(policy_config, sort_dicts=True)}",
        f"CLOUDFILE_OIDC_ENABLED = {oidc_enabled!r}",
        f"CLOUDFILE_OIDC_CONFIG = {pprint.pformat(oidc_config, sort_dicts=True)}",
        f"CLOUDFILE_OIDC_JIT_ENABLED = {oidc_jit_enabled!r}",
        f"CLOUDFILE_WEBDAV_SERVICE_ENABLED = {webdav_enabled!r}",
        f"CLOUDFILE_AUTHORIZATION_ENABLED = {authorization_enabled!r}",
        f"CLOUDFILE_LOCAL_EDIT_ENABLED = {local_edit_enabled!r}",
        f"CLOUDFILE_TRANSFER_ENABLED = {transfer_enabled!r}",
    ]
    lines.extend(
        f"{name} = {pprint.pformat(value, sort_dicts=True)}"
        for name, value in authentik.items()
    )
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
        updated = current[:begin] + block + current[end:]
    else:
        separator = "" if not current or current.endswith("\n") else "\n"
        updated = current + separator + block

    if updated == current:
        return False

    with open(path, "w", encoding="utf-8") as settings_file:
        settings_file.write(updated)
    return True


def write_policy_worker_hooks(path, environment=None):
    """Manage only our block; preserve and compose existing Gunicorn hooks."""
    environment = os.environ if environment is None else environment
    enabled = _boolean(environment, "CLOUDFILE_POLICY_WORKER_HOOKS", False)
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
    block = ""
    if enabled:
        block = '\n'.join((begin_marker,
            "_cf_previous_post_worker_init = globals().get('post_worker_init')",
            "_cf_previous_worker_exit = globals().get('worker_exit')",
            "def post_worker_init(worker):",
            "    if _cf_previous_post_worker_init is not None:",
            "        _cf_previous_post_worker_init(worker)",
            "    from cloudfile_extensions.authorization.gunicorn import post_worker_init as cf_init",
            "    cf_init(worker)",
            "def worker_exit(server, worker):",
            "    try:",
            "        if _cf_previous_worker_exit is not None:",
            "            _cf_previous_worker_exit(server, worker)",
            "    finally:",
            "        from cloudfile_extensions.authorization.gunicorn import worker_exit as cf_exit",
            "        cf_exit(server, worker)", end_marker, ""))
    updated = base + ("\n" if block and base and not base.endswith("\n") else "") + block
    if updated == current:
        return False
    with open(path, "w", encoding="utf-8") as target:
        target.write(updated)
    return True
