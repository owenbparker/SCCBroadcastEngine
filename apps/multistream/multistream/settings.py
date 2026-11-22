"""The saved settings (data/multistream/config.json): each platform's stream
key and whether it's on. That's all Multistream needs: no logins, no
platform APIs. Paste a key, switch the platform on, and it goes live when
OBS / vMix starts streaming.

Stream keys are kept here in plain text, on this PC only; the control panel
is only reachable from this PC.

Older versions also kept logins, stream profiles and stream info here; those
are left in the file untouched (never thrown away), just no longer used.
"""

import copy
import json
import os
import re
import threading
import uuid

from .config import SETTINGS_FILE
from .log import log

# Video modes for a destination.
COPY = "copy"           # OBS's stream as it is (no re-encode, almost no CPU)
CROP = "crop"           # the middle of OBS's 16:9 picture as 9:16, re-encoded
VERTICAL = "vertical"   # OBS's second, vertical output (stream key "vertical")
ENCODE = "encode"       # OBS's picture as it is, re-encoded at a lower bitrate (e.g. Twitch at 8000
                        # while YouTube gets OBS's 14000 copied)
VIDEO_MODES = (COPY, CROP, VERTICAL, ENCODE)
REENCODED = (CROP, ENCODE)

PLATFORMS = {
    # fixed: the platform's server never changes, so its stream key is all it needs.
    "youtube": {"name": "YouTube", "server": "rtmp://a.rtmp.youtube.com/live2", "fixed": True,
                "help": "YouTube Studio > Create > Go live > Stream > Stream key (use a reusable key)"},
    "twitch": {"name": "Twitch", "server": "rtmp://live.twitch.tv/app", "fixed": True,
               "help": "Twitch Creator Dashboard > Settings > Stream > Primary Stream key"},
    "x": {"name": "X", "server": "",
          "help": "X Media Studio > Producer > Sources > Create source: copy its RTMP URL and Stream key"},
    "tiktok": {"name": "TikTok", "server": "", "video": CROP,
               "help": "TikTok LIVE Center > Go LIVE > Stream key: copy the Server URL and Stream key (they can change every time you go live)"},
    "facebook": {"name": "Facebook", "server": "rtmps://live-api-s.facebook.com:443/rtmp/", "fixed": True,
                 "help": "Facebook Live Producer > Streaming software > Stream key (turn on \"Use a persistent stream key\")"},
    "custom": {"name": "RTMP", "server": "", "help": "Any RTMP or RTMPS server (Kick, Trovo, a second YouTube channel...) and its stream key"},
}
DEFAULT_ORDER = ("youtube", "twitch", "x", "tiktok", "facebook")


def new_destination(platform, **fields):
    p = PLATFORMS.get(platform, PLATFORMS["custom"])
    d = {"id": platform if platform != "custom" else "rtmp-" + uuid.uuid4().hex[:6],
         "platform": platform if platform in PLATFORMS else "custom",
         "name": p["name"], "enabled": False, "server": p["server"], "key": "",
         "video": p.get("video", COPY), "bitrate": 6000}
    d.update(fields)
    return d


def defaults():
    return {"destinations": [new_destination(p) for p in DEFAULT_ORDER],
            "lan": False,          # let other PCs on the network stream in
            "encoder": "auto"}     # for re-encoded (cropped) outputs


def split_url(text):
    """A whole stream URL pasted as the key -> (server, key):
    "rtmp://live.twitch.tv/app/live_123" -> ("rtmp://live.twitch.tv/app", "live_123")."""
    m = re.match(r"^(rtmps?://[^/\s]+(?::\d+)?/(?:[^\s]*/)?)([^/\s]+)$", text, re.I)
    if not m:
        return None
    return m.group(1).rstrip("/"), m.group(2)


def clean_key(text):
    """A stream key as pasted: no spaces, line breaks or invisible characters
    (copying from a web page often brings some along)."""
    return re.sub(r"[\s\u200b-\u200d\ufeff]+", "", str(text or ""))


def clean_destination(d, old=None):
    """A destination as sent by the control panel -> a saved one. Raises ValueError."""
    out = dict(old or new_destination(str(d.get("platform") or "custom")))
    for field in ("name", "server"):
        if field in d:
            out[field] = str(d[field] or "").strip()
    if "key" in d:
        key = clean_key(d["key"])
        whole = split_url(key) if re.match(r"^rtmps?://", key, re.I) else None
        if whole:
            # The whole address pasted into the key box: keep the key, and the
            # server too where the platform's server isn't fixed.
            server, key = whole
            if not PLATFORMS.get(out["platform"], {}).get("fixed") and "server" not in d:
                out["server"] = server
        elif re.match(r"^rtmps?://", key, re.I):
            raise ValueError("That looks like the server address. Paste the stream key here (the server is already set)")
        out["key"] = key
    if "enabled" in d:
        out["enabled"] = bool(d["enabled"])
    if "video" in d:
        if d["video"] not in VIDEO_MODES:
            raise ValueError(f"Unknown video mode: {d['video']}")
        out["video"] = d["video"]
    if "bitrate" in d:
        try:
            out["bitrate"] = max(500, min(20000, int(d["bitrate"])))
        except (TypeError, ValueError):
            raise ValueError("Bitrate must be a number (kbps)")
    if out["server"] and not re.match(r"^rtmps?://", out["server"], re.I):
        raise ValueError("The server should start with rtmp:// or rtmps://")
    if not out["name"]:
        out["name"] = PLATFORMS.get(out["platform"], PLATFORMS["custom"])["name"]
    return out


def server_of(d):
    """Where it streams to: YouTube, Twitch and Facebook always use their
    own server (only their stream key is asked for)."""
    p = PLATFORMS.get(d.get("platform"), {})
    return p["server"] if p.get("fixed") else (d.get("server") or "").strip()


def missing(d):
    """What a destination still needs before it can go live, or ""."""
    if not server_of(d):
        return "Paste the server URL and stream key"
    if not (d.get("key") or "").strip() and d.get("platform") != "custom":
        return "Paste the stream key"
    return ""


def target_url(d):
    """The full address FFmpeg pushes to: server + stream key."""
    server, key = server_of(d), (d.get("key") or "").strip()
    if not key:
        return server
    return server.rstrip("/") + "/" + key


class Settings:
    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.data = defaults()
        self.load()

    def load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError) as e:
            log(f"Couldn't read {os.path.basename(self.path)} ({e}); using defaults", "warn")
            return
        data = defaults()
        # (everything in the file is kept, even what this version doesn't use)
        data.update({k: v for k, v in saved.items() if k != "destinations"})
        if isinstance(saved.get("destinations"), list):
            data["destinations"] = [{**new_destination(d.get("platform", "custom")), **d}
                                    for d in saved["destinations"] if isinstance(d, dict) and d.get("id")]
        self.data = data

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self.data)

    def destinations(self):
        return self.snapshot()["destinations"]

    def update_destination(self, d):
        """Add (no id or unknown id) or change one destination."""
        with self._lock:
            dests = self.data["destinations"]
            i = next((i for i, x in enumerate(dests) if x["id"] == d.get("id")), None)
            if i is None:
                new = clean_destination(d)
                dests.append(new)
            else:
                new = dests[i] = clean_destination(d, dests[i])
            self.save()
            return new

    def remove_destination(self, dest_id):
        with self._lock:
            self.data["destinations"] = [d for d in self.data["destinations"] if d["id"] != dest_id]
            self.save()

    def set(self, **values):
        with self._lock:
            for k, v in values.items():
                if k not in ("lan", "encoder"):
                    raise ValueError(f"Unknown setting: {k}")
                self.data[k] = v
            self.save()
