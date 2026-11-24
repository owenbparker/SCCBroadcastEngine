"""Recolours the "Sakura Class Broadcast HUD Val" copy of the SCC 2027 VALORANT HUD.
Only that copy's saved changes are touched (never SCC 2027 itself), and only the
background colour / background picture of the parts listed below; every other
change already saved on the copy is kept. The copy's earlier version stays in
HUD Builder > Game HUDs > Versions, so it can be undone from there.
Run:  python apply_sakura.py [http://localhost:PORT]"""
import json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
COPY_NAME = "sakura"          # matched case-insensitively in the copy's name
BASE = "val-scc2027"
MAROON = "#4A1F36"
# part selector -> what to set (bg colour, and a background picture from this folder)
PARTS = {
    "#top > div:nth-of-type(3) > div:nth-of-type(1)": {"bg": MAROON},          # top bar, left half
    "#top > div:nth-of-type(4) > div:nth-of-type(1)": {"bg": MAROON},          # top bar, right half
    "#event": {"bg": MAROON},                                                  # event strip
    "#sponsor": {"bg": MAROON},                                                # sponsor box
    "#sponsor::before": {"bg": MAROON},                                        # join under the strip
    "#board > div:nth-of-type(1)": {"bg": "#111823", "pic": "sakura-texture.svg"},   # buy-phase board
    "#tracker": {"bg": "#111823", "pic": "sakura-texture.svg"},                # round tracker panel
    "#tracker > div:nth-of-type(1)": {"bg": MAROON, "pic": "sakura-maroon.svg"},     # tracker team box
    "#tracker > div:nth-of-type(2)": {"bg": MAROON, "pic": "sakura-maroon.svg"},     # tracker team box
    "#tracker > div:nth-of-type(3)": {"bg": MAROON, "pic": "sakura-maroon.svg"},     # tracker round grid
    "#rwin > div:nth-of-type(1)": {"pic": "roundwin-sakura.png"},             # round win background
    "#rwin > div:nth-of-type(2)": {"pic": "sakura-bar.svg"},                  # round win opening flash (was yellow)
    "#rwin > div:nth-of-type(5)": {"pic": "sakura-bar.svg"},                  # round win bar (was yellow)
    "#rwin > div:nth-of-type(6)": {"color": "#FFF7FA"},                       # round win bar text
    "#rwin > div:nth-of-type(6) span + span::before": {"bg": "#FFF7FA"},      # the dots between its words
}


def call(url, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data, {"Content-Type": ctype} if data is not None else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def find_server(arg):
    tries = [arg] if arg else [f"http://localhost:{p}" for p in (8778, 8787, 8788, 8796, 8780, 8790)]
    for base in tries:
        try:
            for c in call(base.rstrip("/") + "/hudedit/copies").get("copies", []):
                if c.get("base") == BASE or str(c.get("key", "")).startswith(BASE):
                    return base.rstrip("/")
        except Exception:
            pass
    sys.exit("Couldn't reach the VALORANT HUD. Open SCC Broadcast Engine, then run again with its address, "
             "e.g. python apply_sakura.py http://localhost:PORT")


def main():
    base = find_server(sys.argv[1] if len(sys.argv) > 1 else "")
    copies = [c for c in call(base + "/hudedit/copies")["copies"]
              if COPY_NAME in str(c.get("name", "")).lower() and str(c.get("key", c.get("base", ""))).startswith(BASE)]
    if len(copies) != 1:
        sys.exit("Expected exactly one Sakura copy of SCC 2027, found: " + ", ".join(c.get("name", "?") for c in copies))
    copy = copies[0]
    key = copy.get("key") or f"{BASE}.c{copy['id']}"
    print(f"Recolouring '{copy['name']}' ({key}) on {base}")
    pics = {}
    for spec in PARTS.values():
        name = spec.get("pic")
        if name and name not in pics:
            with open(os.path.join(HERE, name), "rb") as f:
                pics[name] = call(base + "/hudedit/upload?name=" + name, raw=f.read(),
                              ctype="image/png" if name.endswith(".png") else "image/svg+xml")["name"]
    doc = call(base + "/hudedit/edits?design=" + key)
    edits = {k: doc.get(k) for k in ("rules", "added", "fonts", "settings")}
    rules = edits["rules"] = dict(edits.get("rules") or {})
    for sel, spec in PARTS.items():
        r = dict(rules.get(sel) or {})
        for k in ("bg", "color"):
            if spec.get(k):
                r[k] = spec[k]
        if spec.get("pic"):
            r["img"], r["imgKind"] = pics[spec["pic"]], "bg"
        rules[sel] = r
    out = call(base + "/hudedit/save", {"design": key, "edits": edits, "base_rev": doc.get("rev", 0)})
    print("Saved, version", out.get("rev"), "- the copy updates on air within a second.")


if __name__ == "__main__":
    main()
