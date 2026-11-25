"""Tactical timeouts read off the screen (2026-11-25, owen: "automatically
read timeouts").

The reader sees the game's timeout banner (reader.read_timeout) on each full
read: "starting" then "active", which side called it and the seconds left.
TimeoutWatch turns those readings into a timeout with a start and an end:

- it starts after two readings running (one frame isn't enough to put a card
  on the broadcast), and is put on the calling team (left/right of the
  screen, from who is attacking);
- it ends when the banner hasn't been seen for END_AFTER seconds (the reader
  only reads every second or so, and a frame can be missed), or at the
  latest MAX_LENGTH after it started.

The app (HudApp._timeout_reading) uses the start to use up one of that team's
timeouts and show its timeout card, and the end to take the card off again,
the same as the Control page's "Timeout: <team>" button does by hand.
"""

import time

SIDES = ("left", "right")


class TimeoutWatch:
    START_READS = 2      # banner readings running before it counts
    END_AFTER = 4.0      # seconds without the banner before it's over
    MAX_LENGTH = 100.0   # a timeout is a minute (+ a few seconds' warning)

    def __init__(self):
        self._spent = False
        self.reset()

    def reset(self):
        self.team = ""        # "left" / "right": the timeout running now ("" none)
        self.state = ""       # "starting" / "active"
        self.seconds = None   # left in the timeout (active), when read
        self.started_at = 0.0
        self.seen_at = 0.0
        self._run = 0
        self._caller = None

    def live(self):
        """{"state", "team", "seconds"} of the timeout running, or {}."""
        if not self.team:
            return {}
        return {"state": self.state, "team": self.team, "seconds": self.seconds}

    def step(self, reading, attackers, now=None):
        """One full read: reading is reader.read_timeout's (None = no banner
        on that frame), attackers the attacking side ("left"/"right", None if
        unknown). Returns ("start", team), ("end", team) or None."""
        now = time.time() if now is None else now
        if reading and self._spent:
            return None   # (the banner of a timeout already ended by MAX_LENGTH)
        if reading:
            self.seen_at = now
            caller = reading.get("caller")
            team = None
            if caller in ("attackers", "defenders") and attackers in SIDES:
                team = attackers if caller == "attackers" else ("right" if attackers == "left" else "left")
            if self.team:
                self.state = reading.get("state") or self.state
                self.seconds = reading.get("seconds")
                if now - self.started_at > self.MAX_LENGTH:
                    end = self._end()
                    self._spent = True
                    return end
                return None
            self._run += 1
            self._caller = team or self._caller
            if self._run >= self.START_READS and self._caller:
                self.team, self.state = self._caller, reading.get("state") or "active"
                self.seconds = reading.get("seconds")
                self.started_at = now
                self._run = 0
                return ("start", self.team)
            return None
        self._run = 0
        self._caller = None
        self._spent = False
        return self.check(now)

    def check(self, now=None):
        """The end of a running timeout by the clock (no banner for a while):
        ("end", team) or None."""
        now = time.time() if now is None else now
        if self.team and (now - self.seen_at > self.END_AFTER or now - self.started_at > self.MAX_LENGTH):
            return self._end()
        return None

    def _end(self):
        team = self.team
        self.reset()
        return ("end", team)
