import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multistream import procs  # noqa: E402
from multistream.config import tool  # noqa: E402
from multistream.relay import (CROP_FILTER, Ingest, Output, Relay, explain, ffmpeg_command,  # noqa: E402
                               mediamtx_config, redact)
from multistream.settings import CROP, ENCODE, VERTICAL, Settings, clean_destination, missing, new_destination, target_url  # noqa: E402


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults_have_every_platform_off(self):
        s = Settings(self.path)
        self.assertEqual([d["id"] for d in s.destinations()], ["youtube", "twitch", "x", "tiktok", "facebook"])
        self.assertFalse(any(d["enabled"] for d in s.destinations()))
        self.assertEqual(next(d for d in s.destinations() if d["id"] == "tiktok")["video"], CROP)

    def test_saves_and_loads(self):
        s = Settings(self.path)
        s.update_destination({"id": "twitch", "key": " live_123 ", "enabled": True})
        s.update_destination({"platform": "custom", "name": "Kick", "server": "rtmps://kick.example/app"})
        again = Settings(self.path)
        twitch = next(d for d in again.destinations() if d["id"] == "twitch")
        self.assertEqual((twitch["key"], twitch["enabled"]), ("live_123", True))
        self.assertEqual(again.destinations()[-1]["name"], "Kick")
        self.assertTrue(again.destinations()[-1]["id"].startswith("rtmp-"))
        again.remove_destination(again.destinations()[-1]["id"])
        self.assertEqual(len(Settings(self.path).destinations()), 5)

    def test_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            clean_destination({"platform": "custom", "server": "http://example.com"})
        with self.assertRaises(ValueError):
            clean_destination({"platform": "custom", "video": "sideways"})
        self.assertEqual(clean_destination({"platform": "custom", "bitrate": 99999})["bitrate"], 20000)

    def test_broken_file_falls_back_to_defaults(self):
        with open(self.path, "w") as f:
            f.write("{nope")
        self.assertEqual(len(Settings(self.path).destinations()), 5)

    def test_target_url(self):
        self.assertEqual(target_url({"server": "rtmp://a.rtmp.youtube.com/live2/", "key": "abc"}),
                         "rtmp://a.rtmp.youtube.com/live2/abc")
        self.assertEqual(target_url({"server": "rtmps://live-api-s.facebook.com:443/rtmp/", "key": "FB-1"}),
                         "rtmps://live-api-s.facebook.com:443/rtmp/FB-1")
        self.assertEqual(target_url({"server": "rtmp://x/full/url", "key": ""}), "rtmp://x/full/url")


class CommandTest(unittest.TestCase):
    def test_copy_does_not_reencode(self):
        d = new_destination("twitch", key="k")
        args = ffmpeg_command(d, "rtmp://127.0.0.1:1935/live/main", ffmpeg="ffmpeg")
        self.assertIn("copy", args)
        self.assertNotIn("-vf", args)
        self.assertEqual(args[-1], "rtmp://live.twitch.tv/app/k")
        self.assertEqual(args[args.index("-i") + 1], "rtmp://127.0.0.1:1935/live/main")

    def test_crop_reencodes_with_the_chosen_encoder(self):
        d = new_destination("tiktok", server="rtmp://push.example/game", key="k", bitrate=4000)
        args = ffmpeg_command(d, "rtmp://127.0.0.1:1935/live/main", encoder="h264_nvenc", ffmpeg="ffmpeg")
        self.assertEqual(args[args.index("-vf") + 1], CROP_FILTER)
        self.assertEqual(args[args.index("-c:v") + 1], "h264_nvenc")
        self.assertEqual(args[args.index("-b:v") + 1], "4000k")

    def test_encode_reencodes_the_whole_picture_at_its_bitrate(self):
        d = new_destination("twitch", key="k", video=ENCODE, bitrate=8000)
        args = ffmpeg_command(d, "rtmp://127.0.0.1:1935/live/main", encoder="h264_nvenc", ffmpeg="ffmpeg")
        self.assertEqual(args[args.index("-vf") + 1], "format=nv12")
        self.assertEqual(args[args.index("-c:v") + 1], "h264_nvenc")
        self.assertEqual(args[args.index("-b:v") + 1], "8000k")
        self.assertIn("-force_key_frames", args)
        self.assertEqual(clean_destination({"video": ENCODE}, d)["video"], ENCODE)

    def test_mediamtx_config(self):
        self.assertIn("rtmpAddress: 127.0.0.1:1935", mediamtx_config(False))
        self.assertIn("rtmpAddress: :1935", mediamtx_config(True))
        self.assertIn("apiAddress: 127.0.0.1:", mediamtx_config(True))

    def test_keys_kept_out_of_messages(self):
        self.assertEqual(redact("rtmp://x/app/live_abc123: I/O error", {"key": "live_abc123"}), "rtmp://x/app/••••: I/O error")

    def test_explain(self):
        self.assertIn("server address", explain(["[tcp @ 0] Connection to tcp://x:1935 failed: Connection refused"], 1))
        self.assertIn("stream key", explain(["rtmp://x/app/••••: Input/output error", "Error opening output files: Input/output error"], 1))
        self.assertEqual(explain([], 3), "FFmpeg stopped (exit code 3)")


class FakeIngest:
    def __init__(self, paths=None):
        self.paths, self.rates, self.lan, self.rtmp_port, self.error = {}, {}, False, 1935, None

    def source(self, vertical=False):
        return Ingest.source(self, vertical)

    def url(self, path):
        return "rtmp://127.0.0.1:1935/" + path

    def alive(self):
        return True


class WatcherTest(unittest.TestCase):
    """The watcher's decisions, without starting any programs."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.settings = Settings(os.path.join(self.dir, "config.json"))
        self.ingest = FakeIngest()
        self.relay = Relay(self.settings, self.ingest)
        self.relay.encoder = "libx264"
        self.started = []
        self.real_start = Output.start
        Output.start = lambda out, args: (self.started.append(out.dest["id"]), setattr(out, "status", "starting"))

    def tearDown(self):
        Output.start = self.real_start
        shutil.rmtree(self.dir, ignore_errors=True)

    def status(self):
        return {o["id"]: o["status"] for o in self.relay.state()["outputs"]}

    def test_waits_for_obs_then_starts_what_is_on(self):
        self.settings.update_destination({"id": "youtube", "key": "k", "enabled": True})
        self.settings.update_destination({"id": "x", "enabled": True})    # no server yet
        self.relay.tick()
        self.assertEqual(self.status()["youtube"], "waiting")
        self.assertEqual(self.status()["x"], "setup")
        self.assertEqual(self.status()["twitch"], "off")
        self.ingest.paths = {"live/main": {"ready": True}}
        self.relay.tick()
        self.assertEqual(self.started, ["youtube"])

    def test_vertical_needs_the_vertical_feed(self):
        self.settings.update_destination({"id": "tiktok", "server": "rtmp://t/game", "key": "k", "enabled": True, "video": VERTICAL})
        self.ingest.paths = {"live/main": {"ready": True}}
        self.relay.tick()
        self.assertEqual(self.status()["tiktok"], "waiting")
        self.ingest.paths["live/vertical"] = {"ready": True}
        self.relay.tick()
        self.assertEqual(self.started, ["tiktok"])
        self.assertEqual(self.ingest.source(), "live/main")
        self.assertEqual(self.ingest.source(vertical=True), "live/vertical")


class StreamKeyTest(unittest.TestCase):
    """Multistream works off stream keys alone."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_key_is_all_youtube_twitch_and_facebook_need(self):
        s = Settings(self.path)
        for d in s.destinations():
            self.assertTrue(missing(d))
        s.update_destination({"id": "twitch", "key": "live_123"})
        tw = next(d for d in s.destinations() if d["id"] == "twitch")
        self.assertEqual(missing(tw), "")
        self.assertEqual(target_url(tw), "rtmp://live.twitch.tv/app/live_123")
        # (an old version's edited server doesn't matter: the platform's own is used)
        s.update_destination({"id": "twitch", "server": "rtmp://wrong.example/app"})
        self.assertEqual(target_url(next(d for d in s.destinations() if d["id"] == "twitch")), "rtmp://live.twitch.tv/app/live_123")
        x = next(d for d in s.destinations() if d["id"] == "x")
        self.assertEqual(missing({**x, "key": "abc"}), "Paste the server URL and stream key")

    def test_pasted_keys_are_cleaned(self):
        d = clean_destination({"key": " abcd-efgh\n-ijkl\u200b "}, new_destination("youtube"))
        self.assertEqual(d["key"], "abcd-efgh-ijkl")
        # the whole address pasted as the key
        d = clean_destination({"key": "rtmp://live.twitch.tv/app/live_9_x"}, new_destination("twitch"))
        self.assertEqual(d["key"], "live_9_x")
        d = clean_destination({"key": "rtmps://fa1.global-contribute.live-video.net:443/app/sk_us-east_abc"},
                              new_destination("custom", name="Kick", id="k"))
        self.assertEqual((d["server"], d["key"]), ("rtmps://fa1.global-contribute.live-video.net:443/app", "sk_us-east_abc"))
        d = clean_destination({"key": "FB-1234-0-Abc?s_bl=1&s_ps=1"}, new_destination("facebook"))
        self.assertEqual(target_url(d), "rtmps://live-api-s.facebook.com:443/rtmp/FB-1234-0-Abc?s_bl=1&s_ps=1")
        with self.assertRaises(ValueError):   # the server pasted into the key box
            clean_destination({"key": "rtmp://a.rtmp.youtube.com/"}, new_destination("youtube"))

    def test_old_settings_are_kept(self):
        """Logins, profiles and stream info from older versions stay in the file."""
        old = {"destinations": [new_destination("twitch", enabled=True, key="k", account="SCC", chat="scc")],
               "tokens": {"twitch": "refresh"}, "profiles": [{"name": "Main", "platforms": ["twitch"], "info": {"title": "T"}}],
               "profile": "Main", "lan": True}
        with open(self.path, "w") as f:
            json.dump(old, f)
        s = Settings(self.path)
        s.update_destination({"id": "twitch", "key": "k2"})
        with open(self.path) as f:
            saved = json.load(f)
        for k in ("tokens", "profiles", "profile"):
            self.assertEqual(saved[k], old[k])
        self.assertTrue(saved["lan"])
        tw = saved["destinations"][0]
        self.assertEqual((tw["key"], tw["account"], tw["chat"], tw["enabled"]), ("k2", "SCC", "scc", True))

    def test_switched_on_without_a_key_says_so(self):
        s = Settings(self.path)
        s.update_destination({"id": "youtube", "enabled": True})
        relay = Relay(s, FakeIngest())
        relay.ingest.paths = {"live/main": {}}
        relay.tick()
        self.assertEqual((relay.outputs["youtube"].status, relay.outputs["youtube"].message), ("setup", "Paste the stream key"))


class AppTest(unittest.TestCase):
    """The panel's API: every change applies at once (no Save)."""

    def test_api(self):
        import urllib.request
        from multistream import app as appmod
        work = tempfile.mkdtemp()
        settings = Settings(os.path.join(work, "config.json"))
        relay = Relay(settings, FakeIngest())
        relay.start = lambda: None
        relay.stop = lambda: None
        a = appmod.StreamApp(settings, relay)
        httpd = appmod.start(a, 0)
        port = httpd.server_address[1]

        def post(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        try:
            st = post("/api/destination", {"id": "youtube", "key": "yt-key"})
            yt = next(d for d in st["destinations"] if d["id"] == "youtube")
            self.assertEqual((yt["key"], yt["missing"], yt["fixed"]), ("yt-key", "", True))
            st = post("/api/destination", {"id": "youtube", "enabled": True})
            self.assertTrue(next(d for d in st["destinations"] if d["id"] == "youtube")["enabled"])
            self.assertTrue(Settings(os.path.join(work, "config.json")).destinations()[0]["enabled"])   # saved
            st = post("/api/destination", {"platform": "custom", "name": "Kick", "server": "rtmps://k.example/app", "key": "s"})
            self.assertEqual(st["destinations"][-1]["name"], "Kick")
            for gone in ("/api/save", "/api/login", "/api/profile/select"):
                with self.assertRaises(urllib.error.HTTPError):
                    post(gone, {})
        finally:
            appmod.stop(a)
            shutil.rmtree(work, ignore_errors=True)


@unittest.skipUnless(os.path.isfile(tool("mediamtx")) and shutil.which(tool("ffmpeg")),
                     "needs MediaMTX and FFmpeg (python tools/fetch_binaries.py)")
class EndToEndTest(unittest.TestCase):
    """A test pattern into the RTMP server, out through a copied and a
    cropped destination that point back at the same server."""

    def test_self_test(self):
        """The panel's "Test on this PC" (and the build's smoke test)."""
        from multistream import selftest
        ok, results = selftest.run()
        self.assertTrue(ok, results)

    def test_relay(self):
        from multistream.selftest import free_port
        port, api = free_port(), free_port()
        work = tempfile.mkdtemp()
        settings = Settings(os.path.join(work, "config.json"))
        out = f"rtmp://127.0.0.1:{port}/out"
        settings.data["destinations"] = [
            new_destination("custom", id="a", name="A", enabled=True, server=out, key="a"),
            new_destination("custom", id="b", name="B", enabled=True, server=out, key="b", video=CROP, bitrate=1500),
            new_destination("custom", id="c", name="C", enabled=True, server=out, key="c", video=ENCODE, bitrate=1000),
        ]
        relay = Relay(settings, Ingest(rtmp_port=port, api_port=api, data_dir=work))
        relay.start()
        pub = procs.popen([tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-re",
                           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine",
                           "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-t", "60", "-f", "flv", f"rtmp://127.0.0.1:{port}/live/main"])
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if {"out/a", "out/b", "out/c"} <= set(relay.ingest.paths) and \
                        all(o["status"] == "live" for o in relay.state()["outputs"]):
                    break
                time.sleep(1)
            state = relay.state()
            self.assertEqual(state["ingest"]["status"], "live", json.dumps(state))
            self.assertTrue({"out/a", "out/b", "out/c"} <= set(relay.ingest.paths), json.dumps(state))
            self.assertTrue(all(o["status"] == "live" for o in state["outputs"]), json.dumps(state))
            # OBS stops: the outputs stop with it.
            procs.stop(pub)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and relay.state()["ingest"]["status"] == "live":
                time.sleep(1)
            time.sleep(1.5)
            self.assertEqual({o["status"] for o in relay.state()["outputs"]}, {"waiting"})
        finally:
            procs.stop(pub)
            relay.stop()
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
