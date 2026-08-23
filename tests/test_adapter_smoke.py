"""Does the plugin import and construct at all?

Deliberately shallow. The camera, the printer, and OctoPrint's plugin
lifecycle need hardware or a running server; the failures this catches
need neither -- a bad import, a kwarg the installed bitbang does not
accept, a version floor that is not actually satisfied. Those break the
plugin at startup on every Pi at once, and nothing else here would
notice before a user did.
"""

import pytest

aiortc = pytest.importorskip("aiortc")
bitbang = pytest.importorskip("bitbang")


async def _app(scope, receive, send):
    pass


def test_adapter_constructs_without_hardware():
    """No camera on a CI runner: the adapter must fall back, not raise."""
    from octoprint_bitbang.octoprint_adapter import OctoPrintBitBang

    a = OctoPrintBitBang(_app, ephemeral=True)
    assert a.product == "octoprint"
    assert a.install_hint and "Plugin Manager" in a.install_hint


def test_reports_the_installed_plugin_version():
    """The update notice must name the plugin's version, not the
    library's -- a plugin user upgrades the plugin."""
    from octoprint_bitbang import __plugin_version__
    from octoprint_bitbang.octoprint_adapter import OctoPrintBitBang

    a = OctoPrintBitBang(_app, ephemeral=True)
    assert a.product_version == __plugin_version__
    assert a.product_version != bitbang.__version__ or __plugin_version__ == bitbang.__version__


def test_bitbang_floor_is_satisfied():
    """pyproject pins bitbang>=0.1.56 because the adapter passes kwargs
    older releases reject. If the installed library is older, the two
    tests above would fail with a confusing TypeError instead."""
    import inspect
    from bitbang.adapter import BitBangBase

    params = inspect.signature(BitBangBase.__init__).parameters
    for kw in ("product", "product_version", "install_hint"):
        assert kw in params, f"installed bitbang {bitbang.__version__} predates {kw}"


def test_caller_can_still_override():
    """setdefault, not assignment: an embedder deeper down keeps control."""
    from octoprint_bitbang.octoprint_adapter import OctoPrintBitBang

    a = OctoPrintBitBang(_app, ephemeral=True, product="something-else")
    assert a.product == "something-else"
