#!/usr/bin/env python3
"""Validate v0.4 bootstrap config without importing production bootstrap."""
import importlib.util
from pathlib import Path

file = Path(__file__).with_name("test-bootstrap-settings.py")
spec = importlib.util.spec_from_file_location("cf_bootstrap_checks", file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def configuration(env):
    block = module.load("_settings_block_v04_preview_embed", env)()
    return module.evaluate(block)


def test_default():
    config = configuration({})
    assert config["CF_PREVIEW_PROVIDER"] == "eap-fileview"
    assert config["CF_PREVIEW_PUBLIC_URL"] == ""
    assert config["CF_FORMAL_EMBED_RESOURCES"] == {}


def test_custom():
    values = {"CF_PREVIEW_PROVIDER": "native",
              "CF_PREVIEW_PUBLIC_URL": "https://files.example/viewer",
              "CF_FORMAL_EMBED_RESOURCES":
              '{"research":{"repo_id":"11111111-1111-4111-8111-111111111111","root_path":"/"}}'}
    config = configuration(values)
    assert config["CF_PREVIEW_PROVIDER"] == "native"
    assert config["CF_PREVIEW_PUBLIC_URL"] == values["CF_PREVIEW_PUBLIC_URL"]
    assert config["CF_FORMAL_EMBED_RESOURCES"]["research"]["root_path"] == "/"


def test_invalid():
    for bad in ('[]', 'not-json', '42'):
        try:
            configuration({"CF_FORMAL_EMBED_RESOURCES": bad})
        except ValueError:
            pass
        else:
            raise AssertionError("Must reject untrusted JSON map: " + bad)
    try:
        configuration({"CF_PREVIEW_PROVIDER": "unsafe-provider"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unsupported provider must fail validation")


if __name__ == "__main__":
    test_default()
    test_custom()
    test_invalid()
    print("V04 bootstrap: default, custom, invalid settings passed")
