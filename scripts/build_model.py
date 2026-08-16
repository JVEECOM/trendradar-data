#!/usr/bin/env python3
"""Snapshot -> rapportmodel.

De collector schrijft 's nachts een snapshot met alle ruwe meetwaarden. De
renderer wil een compacter model met precies de velden die hij tekent. Dit
script zit daartussen en doet niets anders dan vertalen: alles wat hier
uitkomt staat al in de snapshot of is er rechtstreeks uit af te leiden.

Bewust NIET hier: het duiden van wat er gebeurt. Het veld "why" blijft leeg,
zodat de renderer terugvalt op status_reason - de echte reden uit scoring.py.
Wil de ochtendtaak daar een betere zin van maken, dan mag hij "why" per item
overschrijven voor hij rendert.

Gebruik:
    python build_model.py snapshot.json model.json
    python build_model.py snapshot.json -          # naar stdout
"""
from __future__ import annotations

import json
import sys
from datetime import date

# Alleen deze statussen horen in het rapport. "afgevoerd" laten we weg: die
# staan al niet meer op de watchlist, dus ze zouden één dag lang als geest
# blijven hangen.
REPORT_STATUSES = ("bevestigd", "misschien", "nieuw")


def _days_between(first_seen: str, today: str) -> int | None:
    try:
        a = date.fromisoformat(first_seen)
        b = date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    return max(0, (b - a).days)


def build_item(t: dict, today: str) -> dict:
    """Eén gevolgde term uit de snapshot naar een rapportitem."""
    hist = [float(v) for v in (t.get("score_history") or [])]
    return {
        "term": t.get("term"),
        "label": t.get("label") or t.get("term"),
        "track": t.get("track", "hype"),
        # De collector past status_suggested toe op de watchlist, dus dat is
        # de stand van vandaag; status_before is die van gisteren.
        "status": t.get("status_suggested") or t.get("status") or "misschien",
        "score": t.get("score", 0),
        "score_history": hist,
        "phase": t.get("phase", "nieuw"),
        "sources_present": t.get("sources_present") or [],
        "status_reason": t.get("status_reason", ""),
        "why": "",
        "days_watched": _days_between(t.get("first_seen", ""), today),
        "wikipedia_article": t.get("wikipedia_article"),
    }


def make_headline(items: list[dict], counts: dict) -> str:
    """Feitelijke samenvatting in één zin - geen duiding, alleen tellen.

    De ochtendtaak mag dit overschrijven met iets beters; dit is de
    terugvaloptie zodat het rapport nooit zonder kop staat.
    """
    stijgers = [i for i in items if i.get("phase") == "stijgend"]
    stijgers.sort(key=lambda i: i.get("score") or 0, reverse=True)

    delen = []
    if counts.get("bevestigd"):
        delen.append(f"{counts['bevestigd']} bevestigd")
    if counts.get("misschien"):
        delen.append(f"{counts['misschien']} in de gaten te houden")
    basis = ", ".join(delen) if delen else "nog niets bevestigd"

    if stijgers:
        top = stijgers[0]
        naam = top.get("label") or top.get("term")
        return f"{basis}. Hardste stijger: {naam} ({top.get('score', 0):.0f})."
    return f"{basis}. Geen duidelijke stijgers vandaag."


def build_model(snapshot: dict) -> dict:
    today = snapshot.get("date") or ""
    tracked = snapshot.get("tracked") or []

    items = [build_item(t, today) for t in tracked]
    items = [i for i in items if i["status"] in REPORT_STATUSES]

    counts: dict[str, int] = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1

    return {
        "date": today,
        "generated_at": snapshot.get("finished_at") or snapshot.get("started_at") or "",
        "headline": make_headline(items, counts),
        "counts": counts,
        "items": items,
        "source_status": snapshot.get("source_status") or {},
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    src, dest = sys.argv[1], sys.argv[2]
    with open(src, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    model = build_model(snapshot)
    payload = json.dumps(model, ensure_ascii=False, indent=1)

    if dest == "-":
        sys.stdout.write(payload)
    else:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"geschreven: {dest} ({len(payload)} bytes, {len(model['items'])} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
