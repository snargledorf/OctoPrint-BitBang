import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Provide mock stubs if dependencies (e.g. OctoPrint, Flask, PyAV, aiortc) are
# not installed in the local test environment.
for mod in [
    "av",
    "aiortc",
    "aiortc.contrib",
    "aiortc.contrib.media",
    "aiortc.rtcrtpsender",
    "bitbang",
    "bitbang.proxy",
    "flask",
    "octoprint",
    "octoprint.plugin",
    "octoprint.schema",
    "octoprint.schema.webcam",
    "octoprint.webcams",
]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            mock = MagicMock()
            if mod == "octoprint.plugin":
                for base in (
                    "StartupPlugin",
                    "ShutdownPlugin",
                    "SettingsPlugin",
                    "TemplatePlugin",
                    "AssetPlugin",
                    "BlueprintPlugin",
                    "WebcamProviderPlugin",
                    "WizardPlugin",
                ):
                    cls = type(base, (), {})
                    if base == "BlueprintPlugin":
                        cls.route = staticmethod(lambda *a, **kw: (lambda f: f))
                        cls.csrf_exempt = staticmethod(lambda: (lambda f: f))
                    setattr(mock, base, cls)
            elif mod == "octoprint.schema.webcam":
                class _RatioEnum:
                    four_three = "4:3"
                    sixteen_nine = "16:9"

                class _WebcamCompatibility:
                    def __init__(self, **kwargs):
                        for k, v in kwargs.items():
                            setattr(self, k, v)

                class _Webcam:
                    def __init__(self, **kwargs):
                        for k, v in kwargs.items():
                            setattr(self, k, v)

                mock.RatioEnum = _RatioEnum
                mock.WebcamCompatibility = _WebcamCompatibility
                mock.Webcam = _Webcam
            elif mod == "octoprint.webcams":
                class _WebcamNotAbleToTakeSnapshotException(Exception):
                    pass

                mock.WebcamNotAbleToTakeSnapshotException = (
                    _WebcamNotAbleToTakeSnapshotException
                )
            sys.modules[mod] = mock

sys.modules["octoprint"].plugin = sys.modules["octoprint.plugin"]
sys.modules["octoprint"].schema = sys.modules["octoprint.schema"]
sys.modules["octoprint.schema"].webcam = sys.modules["octoprint.schema.webcam"]
sys.modules["octoprint"].webcams = sys.modules["octoprint.webcams"]

from octoprint_bitbang._plugin import BitBangPlugin


class _FakeResponse:
    def __init__(self, body=b"", status=200, mimetype=None, headers=None):
        self.body = body
        self.status_code = status
        self.mimetype = mimetype
        self.headers = headers or {}


class TestWebcamConfigurationsAndEndpoints(unittest.TestCase):
    def setUp(self):
        self.plugin = BitBangPlugin()
        self.plugin._logger = MagicMock()
        self.plugin._settings = MagicMock()
        self.plugin._settings.get.side_effect = lambda path: (
            "640x480" if path == ["camera_resolution"] else ""
        )

    def test_get_webcam_configurations_exposes_compat_urls_4_3(self):
        configs = self.plugin.get_webcam_configurations()
        self.assertEqual(len(configs), 1)
        cam = configs[0]
        self.assertEqual(cam.name, "bitbang")
        self.assertTrue(cam.canSnapshot)
        self.assertEqual(cam.snapshotDisplay, "/plugin/bitbang/snapshot")
        self.assertIsNotNone(cam.compat)
        self.assertEqual(cam.compat.stream, "/plugin/bitbang/webrtc")
        self.assertEqual(cam.compat.snapshot, "/plugin/bitbang/snapshot")
        self.assertEqual(str(cam.compat.streamRatio), "4:3")
        self.assertEqual(cam.extras["stream"], "/plugin/bitbang/webrtc")
        self.assertEqual(cam.extras["snapshot"], "/plugin/bitbang/snapshot")

    def test_get_webcam_configurations_16_9_ratio(self):
        self.plugin._settings.get.side_effect = lambda path: (
            "1280x720" if path == ["camera_resolution"] else ""
        )
        configs = self.plugin.get_webcam_configurations()
        self.assertEqual(str(configs[0].compat.streamRatio), "16:9")

    def test_strip_non_h264_preserves_audio_section_for_whep(self):
        sdp = (
            "v=0\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96 97 98\r\n"
            "a=rtpmap:96 VP8/90000\r\n"
            "a=rtpmap:97 H264/90000\r\n"
            "a=fmtp:97 packetization-mode=1\r\n"
            "a=rtpmap:98 rtx/90000\r\n"
            "a=fmtp:98 apt=97\r\n"
            "m=audio 9 UDP/TLS/RTP/SAVPF 111 0\r\n"
            "a=rtpmap:111 opus/48000/2\r\n"
            "a=rtpmap:0 PCMU/8000\r\n"
        )
        out = self.plugin._strip_non_h264(sdp)
        self.assertIn("m=video 9 UDP/TLS/RTP/SAVPF 97 98\r\n", out)
        self.assertNotIn("VP8/90000", out)
        self.assertIn("m=audio 9 UDP/TLS/RTP/SAVPF 111 0\r\n", out)
        self.assertIn("a=rtpmap:111 opus/48000/2\r\n", out)
        self.assertIn("a=rtpmap:0 PCMU/8000\r\n", out)

    @patch("octoprint_bitbang._plugin.flask")
    def test_snapshot_endpoint_returns_jpeg(self, mock_flask):
        mock_flask.Response = _FakeResponse
        self.plugin.take_webcam_snapshot = MagicMock(return_value=iter([b"\xff\xd8jpeg\xff\xd9"]))

        resp = self.plugin.webcam_snapshot()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/jpeg")
        self.assertEqual(resp.body, b"\xff\xd8jpeg\xff\xd9")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))

    @patch("octoprint_bitbang._plugin.flask")
    def test_webrtc_get_action_snapshot_delegates_to_snapshot(self, mock_flask):
        mock_flask.request.method = "GET"
        mock_flask.request.args = {"action": "snapshot"}
        self.plugin.webcam_snapshot = MagicMock(return_value="snapshot-response")

        resp = self.plugin.webrtc_stream()
        self.assertEqual(resp, "snapshot-response")
        self.plugin.webcam_snapshot.assert_called_once_with()

    @patch("octoprint_bitbang._plugin.flask")
    def test_webrtc_get_renders_stream_template(self, mock_flask):
        mock_flask.request.method = "GET"
        mock_flask.request.args = {}
        mock_flask.render_template.return_value = "<html/>"

        resp = self.plugin.webrtc_stream()
        self.assertEqual(resp, "<html/>")
        mock_flask.render_template.assert_called_once_with("bitbang_stream.jinja2")

        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "octoprint_bitbang",
            "templates",
            "bitbang_stream.jinja2",
        )
        self.assertTrue(os.path.isfile(template_path))

    @patch("octoprint_bitbang._plugin.asyncio.run_coroutine_threadsafe")
    @patch("octoprint_bitbang._plugin.flask")
    def test_webrtc_post_whep_sdp_returns_201_application_sdp(
        self, mock_flask, mock_run_coro
    ):
        mock_flask.Response = _FakeResponse
        mock_flask.request.method = "POST"
        mock_flask.request.path = "/plugin/bitbang/webrtc"
        mock_flask.request.content_type = "application/sdp"
        mock_flask.request.get_data.return_value = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"

        self.plugin._adapter = MagicMock()
        self.plugin._adapter.player.video = MagicMock()
        self.plugin._adapter._loop = MagicMock()
        self.plugin._adapter.get_ice_servers.return_value = []
        self.plugin._handle_local_offer = MagicMock(return_value="coro")

        fut = MagicMock()
        fut.result.return_value = {"sdp": "v=0\r\na=answer\r\n", "type": "answer"}
        mock_run_coro.return_value = fut

        resp = self.plugin.webrtc_stream()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.mimetype, "application/sdp")
        self.assertEqual(resp.body, "v=0\r\na=answer\r\n")
        self.assertEqual(resp.headers.get("Location"), "/plugin/bitbang/webrtc")

    @patch("octoprint_bitbang._plugin.asyncio.run_coroutine_threadsafe")
    @patch("octoprint_bitbang._plugin.flask")
    def test_webrtc_post_json_returns_json_answer(self, mock_flask, mock_run_coro):
        mock_flask.jsonify.side_effect = lambda d: d
        mock_flask.request.method = "POST"
        mock_flask.request.content_type = "application/json"
        mock_flask.request.get_json.return_value = {
            "sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "type": "offer",
        }

        self.plugin._adapter = MagicMock()
        self.plugin._adapter.player.video = MagicMock()
        self.plugin._adapter._loop = MagicMock()
        self.plugin._adapter.get_ice_servers.return_value = [{"urls": "stun:example"}]
        self.plugin._handle_local_offer = MagicMock(return_value="coro")

        fut = MagicMock()
        fut.result.return_value = {"sdp": "v=0\r\na=answer\r\n", "type": "answer"}
        mock_run_coro.return_value = fut

        resp = self.plugin.local_offer()
        self.assertEqual(resp["sdp"], "v=0\r\na=answer\r\n")
        self.assertEqual(resp["type"], "answer")
        self.assertEqual(resp["ice_servers"], [{"urls": "stun:example"}])


if __name__ == "__main__":
    unittest.main()
