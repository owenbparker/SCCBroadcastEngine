"""Past match results: the Recent Results graphic's matches, kept per
tournament (Global "results", saved with the tournament like its standings).

    results = [{"id", "label": "WEEK 1 - GAME 1", "date": "2026-10-02",
                "team1": "St. Clair Saints", "score1": "3",
                "team2": "Fanshawe Falcons", "score2": "1"}, ...]

Entered on the Tournament page, or imported from a spreadsheet (CSV / Excel:
one match a row, columns found by their titles), or saved from the match on
Global when it ends.

The "Results" data table is for one team (the one the player graphics show,
"Players from" in Control): its latest matches, newest first, with that team
always on the left and its score first:

    {{Results!Team}}, {{Results!Team logo}}, {{Results!Match 1 label}},
    {{Results!Match 1 score}} (3-1), {{Results!Match 1 opponent logo}},
    {{Results!Match 1 result}} (W / L / D), {{Results!Match 1 show}} ...
"""

import re
import uuid

MAX = 400
SLOTS = 8
KEYS = ("label", "date", "team1", "score1", "team2", "score2")


def default():
    return []


def _id():
    return uuid.uuid4().hex[:8]


def _score(v):
    v = str(v if v is not None else "").strip()[:6]
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else v
    except ValueError:
        return v


def clean(results):
    out = []
    for r in (results if isinstance(results, list) else [])[:MAX]:
        if not isinstance(r, dict):
            continue
        x = {"id": str(r.get("id") or "")[:20] or _id()}
        for k in KEYS:
            x[k] = _score(r.get(k)) if k.startswith("score") else re.sub(r"\s+", " ", str(r.get(k) or "")).strip()[:120]
        if x["date"] and not re.match(r"^\d{4}-\d{2}-\d{2}$", x["date"]):
            x["date"] = _date(x["date"])
        if x["team1"] or x["team2"]:
            out.append(x)
    return out


def _date(v):
    """A date as YYYY-MM-DD, from the ways spreadsheets write them ("" if it isn't one)."""
    v = str(v or "").strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", v)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", v)
    if m:   # (month first, as in North America)
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return f"{y}-{int(m[1]):02d}-{int(m[2]):02d}"
    return ""


def _key(r, n):
    # Newest first: by date (no date: as entered, the last entered newest).
    return (r["date"] or "", n)


def for_team(results, team):
    """The team's matches, newest first, the team on the left: [{label, date, team,
    opponent, score, their, result}]. No team picked: every match, as entered."""
    team_low = (team or "").strip().lower()
    out = []
    ordered = sorted(enumerate(results), key=lambda p: _key(p[1], p[0]), reverse=True)
    for _, r in ordered:
        if team_low and team_low not in (r["team1"].lower(), r["team2"].lower()):
            continue
        flip = bool(team_low) and r["team2"].lower() == team_low and r["team1"].lower() != team_low
        us, them = (("team2", "score2"), ("team1", "score1")) if flip else (("team1", "score1"), ("team2", "score2"))
        a, b = r[us[1]], r[them[1]]
        try:
            res = "W" if float(a) > float(b) else "L" if float(a) < float(b) else "D"
        except ValueError:
            res = ""
        out.append({"label": r["label"], "date": r["date"], "team": r[us[0]], "opponent": r[them[0]],
                    "score": f"{a}-{b}" if a or b else "", "us": a, "them": b, "result": res})
    return out


def rows(results, team, find=None, title=""):
    """The "Results" data table. find(name) -> a team from the team list."""
    find = find or (lambda name: None)
    info = find(team) if team else None
    info = info or {}
    matches = for_team(clean(results), team)
    wins = sum(1 for m in matches if m["result"] == "W")
    losses = sum(1 for m in matches if m["result"] == "L")
    out = [["Field", "Value"], ["Team", team or ""], ["Team short", info.get("short", "") or team or ""],
           ["Team logo", info.get("logo", "")], ["Title", title], ["Count", str(len(matches))],
           ["Record", f"{wins}-{losses}" if matches else ""], ["Wins", str(wins)], ["Losses", str(losses)]]
    for n in range(1, SLOTS + 1):
        m = matches[n - 1] if n <= len(matches) else None
        k = f"Match {n}"
        if not m:
            out += [[k + x, ""] for x in (" label", " date", " team", " team logo", " opponent", " opponent short",
                                          " opponent logo", " score", " team score", " opponent score", " result",
                                          " won", " show")]
            continue
        us = find(m["team"]) or {}
        them = find(m["opponent"]) or {}
        out += [[k + " label", m["label"]], [k + " date", m["date"]], [k + " team", m["team"]],
                [k + " team logo", us.get("logo", "") or info.get("logo", "")], [k + " opponent", m["opponent"]],
                [k + " opponent short", them.get("short", "") or m["opponent"]], [k + " opponent logo", them.get("logo", "")],
                [k + " score", m["score"]], [k + " team score", m["us"]], [k + " opponent score", m["them"]],
                [k + " result", m["result"]], [k + " won", "1" if m["result"] == "W" else ""], [k + " show", "1"]]
    return out


# --- importing a spreadsheet --------------------------------------------------------

COLUMNS = {
    "label": r"label|week|round|stage|game|match|title|name",
    "date": r"date|day|played|when",
    "team1": r"team ?1|team ?a|^home|^left|^team$|^us$|^our team",
    "team2": r"team ?2|team ?b|^away|^right|opponent|^vs\.?$|^versus",
    "score1": r"score ?1|score ?a|home score|left score|team ?1 score|team ?a score|^score$|^us$|^for$|our score",
    "score2": r"score ?2|score ?b|away score|right score|team ?2 score|team ?b score|opponent score|their score|^them$|^against$",
}


def _columns(head):
    """Which column is which, from a heading row (None if it isn't one)."""
    head = [str(h or "").strip().lower() for h in head]
    found = {}
    # The scores first ("Team 1 score" isn't Team 1), then the rest.
    for key in ("score1", "score2", "team1", "team2", "date", "label"):
        for i, h in enumerate(head):
            if i in found.values() or not h:
                continue
            if re.search(COLUMNS[key], h):
                found[key] = i
                break
    return found if "team1" in found and "team2" in found else None


SCORE_IN_ONE = re.compile(r"^\s*(\d+)\s*[-–:]\s*(\d+)\s*$")


def from_rows(rows):
    """Matches from a spreadsheet's rows. With a heading row, by its column
    titles; without, the columns are label, date, team 1, score 1, score 2,
    team 2 (or "3-1" in one column between the teams)."""
    rows = [list(r) for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        return []
    cols = _columns(rows[0])
    body = rows[1:] if cols else rows
    out = []
    for r in body:
        cell = lambda i: str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else ""   # noqa: E731
        if cols:
            x = {k: cell(cols.get(k)) for k in KEYS}
            # "3-1" in the one score column
            m = SCORE_IN_ONE.match(x["score1"]) if not x["score2"] else None
            if m:
                x["score1"], x["score2"] = m[1], m[2]
        else:
            cells = [cell(i) for i in range(len(r))]
            one = next((i for i, c in enumerate(cells) if SCORE_IN_ONE.match(c)), None)
            if one is not None and 0 < one < len(cells) - 1:
                m = SCORE_IN_ONE.match(cells[one])
                before, after = cells[:one], cells[one + 1:]
                x = {"team1": before[-1], "score1": m[1], "score2": m[2], "team2": after[0],
                     "label": before[0] if len(before) > 1 else "", "date": before[1] if len(before) > 2 else ""}
            else:
                cells += [""] * (6 - len(cells))
                x = dict(zip(("label", "date", "team1", "score1", "score2", "team2"), cells[:6]))
        if x.get("date"):
            x["date"] = _date(x["date"]) or ""
        if x.get("team1") or x.get("team2"):
            out.append(x)
    return clean(out)


def merge(old, new):
    """Imported matches added to the ones there (a match already there - same
    teams, date and label - is updated, not added again)."""
    old = clean(old)
    key = lambda r: (r["date"], r["label"].lower(), *sorted((r["team1"].lower(), r["team2"].lower())))   # noqa: E731
    at = {key(r): i for i, r in enumerate(old)}
    for r in clean(new):
        if key(r) in at:
            keep = old[at[key(r)]]["id"]
            old[at[key(r)]] = dict(r, id=keep)
        else:
            at[key(r)] = len(old)
            old.append(r)
    return old[:MAX]
