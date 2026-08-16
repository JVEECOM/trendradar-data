#!/usr/bin/env python3
"""Bouwt het dagelijkse TrendRadar-rapport als zelfstandige HTML.

Invoer : het rapportmodel (JSON) dat de ochtendtaak samenstelt uit de
         snapshot plus de korte omschrijvingen die Claude erbij schrijft.
Uitvoer: één HTML-bestand zonder externe afhankelijkheden.

Vormkeuze: elk gevolgd item is een stat tile - huidige score, verandering
t.o.v. gisteren, en een sparkline over het venster van dat spoor (7 / 14 /
30 dagen). Richting wordt door drie dingen tegelijk gedragen: de vorm van
het lijntje, een pijl, en de tekst - nooit door kleur alleen.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime

# --- kleurrollen (dataviz-referentiepalet, gevalideerd in beide modi) ------
LIGHT = {
    "page": "#f9f9f7", "surface": "#fcfcfb",
    "primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "baseline": "#c3c2b7",
    "up": "#2a78d6", "down": "#e34948", "flat": "#898781",
    "border": "rgba(11,11,11,0.10)",
}
DARK = {
    "page": "#0d0d0d", "surface": "#1a1a19",
    "primary": "#ffffff", "secondary": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "baseline": "#383835",
    "up": "#3987e5", "down": "#e66767", "flat": "#898781",
    "border": "rgba(255,255,255,0.10)",
}

TRACKS = [
    ("hype", "Hype &amp; memes", 7, "Korte, virale golven. Venster: 7 dagen."),
    ("roblox", "Roblox-intern", 14, "Wat groeit er binnen het platform zelf. Venster: 14 dagen."),
    ("longterm", "Lange termijn", 30, "Aanhoudende bewegingen. Venster: 30 dagen."),
]

PHASE_LABEL = {
    "stijgend": ("stijgend", "up"),
    "piek": ("op piek", "up"),
    "dalend": ("dalend", "down"),
    "stabiel": ("stabiel", "flat"),
    "nieuw": ("net gespot", "flat"),
}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def sparkline_svg(values: list[float], direction: str, width: int = 168, height: int = 40) -> str:
    """Sparkline: 2px lijn met ronde uiteinden, eindpunt gemarkeerd.

    De markering krijgt een 2px ring in de surface-kleur zodat hij leesbaar
    blijft waar hij de lijn raakt.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return (
            f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="te weinig historie voor een lijn">'
            f'<text x="0" y="{height // 2 + 4}" class="spark-empty">nog te weinig historie</text></svg>'
        )

    pad = 5
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(vals) - 1)

    pts = []
    for i, v in enumerate(vals):
        x = pad + i * step
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        pts.append((x, y))

    path = " ".join(
        ("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts)
    )
    ex, ey = pts[-1]
    lo_lab, hi_lab = f"{lo:.0f}", f"{hi:.0f}"

    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="verloop van {len(vals)} dagen, van {lo_lab} tot {hi_lab}, nu {vals[-1]:.0f}">'
        f'<path d="{path}" fill="none" stroke="var(--{direction})" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="var(--{direction})" '
        f'stroke="var(--surface)" stroke-width="2"/>'
        f'</svg>'
    )


def delta_text(item: dict) -> tuple[str, str]:
    """Pijl + tekst. Dit is het kanaal dat richting echt draagt."""
    hist = item.get("score_history") or []
    phase = item.get("phase", "nieuw")
    label, tone = PHASE_LABEL.get(phase, ("onbekend", "flat"))
    if len(hist) >= 2:
        d = hist[-1] - hist[-2]
        arrow = "↑" if d > 0.5 else ("↓" if d < -0.5 else "→")
        return f"{arrow} {d:+.0f} t.o.v. gisteren · {label}", tone
    return f"→ {label}", tone


def render_tile(item: dict, window: int) -> str:
    hist = [float(v) for v in (item.get("score_history") or [])]
    tail = hist[-window:]
    dtext, tone = delta_text(item)
    score = item.get("score", 0)

    sources = item.get("sources_present") or []
    src_line = ", ".join(sources[:5]) if sources else "nog geen bronnen met genoeg historie"
    why = item.get("why") or item.get("status_reason") or ""

    return f"""
      <article class="tile">
        <div class="tile-head">
          <h3>{esc(item.get('label') or item.get('term'))}</h3>
          <span class="score">{score:.0f}</span>
        </div>
        <div class="tile-chart">{sparkline_svg(tail, tone)}</div>
        <p class="delta delta-{tone}">{esc(dtext)}</p>
        {f'<p class="why">{esc(why)}</p>' if why else ''}
        <p class="meta">Bronnen: {esc(src_line)}</p>
      </article>"""


def render_maybe(item: dict) -> str:
    hist = item.get("score_history") or []
    now = hist[-1] if hist else 0
    why = item.get("why") or item.get("status_reason") or ""
    days = item.get("days_watched")
    tail = f" &middot; {esc(days)} dagen gevolgd" if days else ""
    return f"""
        <li>
          <span class="maybe-name">{esc(item.get('label') or item.get('term'))}</span>
          <span class="maybe-score">{now:.0f}</span>
          <span class="maybe-why">{esc(why)}{tail}</span>
        </li>"""


def render_track(track_key: str, title: str, window: int, blurb: str, model: dict) -> str:
    items = [i for i in model.get("items", []) if i.get("track") == track_key]
    confirmed = [i for i in items if i.get("status") == "bevestigd"]
    maybe = [i for i in items if i.get("status") in ("misschien", "nieuw")]
    dropped = [i for i in items if i.get("status") == "afgevoerd"]

    # Volgorde: wat nu klimt hoort bovenaan, want daar zit de tijdsdruk op.
    # Een hoge score die al aan het wegzakken is, is minder urgent dan een
    # iets lagere die nog stijgt.
    urgency = {"stijgend": 15, "piek": 5, "nieuw": 0, "stabiel": -3, "dalend": -12}
    confirmed.sort(
        key=lambda i: i.get("score", 0) + urgency.get(i.get("phase", "nieuw"), 0),
        reverse=True,
    )
    maybe.sort(key=lambda i: (i.get("score_history") or [0])[-1], reverse=True)

    if confirmed:
        conf_html = '<div class="tiles">' + "".join(render_tile(i, window) for i in confirmed) + "</div>"
    else:
        conf_html = '<p class="empty">Niets bevestigd in dit spoor.</p>'

    # Telling per spoor, zodat je bij het scrollen meteen ziet hoe vol het is.
    bits = []
    if confirmed:
        bits.append(f"{len(confirmed)} bevestigd")
    if maybe:
        bits.append(f"{len(maybe)} in de gaten")
    count_html = f'<span class="track-count">{" &middot; ".join(bits)}</span>' if bits else \
                 '<span class="track-count">leeg</span>'

    maybe_html = ""
    if maybe:
        maybe_html = (
            '<h3 class="sub">Misschien</h3><ul class="maybe">'
            + "".join(render_maybe(i) for i in maybe) + "</ul>"
        )

    dropped_html = ""
    if dropped:
        names = ", ".join(esc(i.get("label") or i.get("term")) for i in dropped)
        dropped_html = f'<p class="dropped">Niet meer gevolgd vanaf nu: {names}</p>'

    return f"""
    <section class="track">
      <div class="track-head">
        <div class="track-title"><h2>{title}</h2>{count_html}</div>
        <p class="blurb">{blurb}</p>
      </div>
      {conf_html}
      {maybe_html}
      {dropped_html}
    </section>"""


def render_sources(model: dict) -> str:
    status = model.get("source_status") or {}
    if not status:
        return ""
    rows = []
    for name, s in sorted(status.items()):
        if s.get("ok"):
            state, cls = "werkte", "ok"
        elif s.get("skipped_reason"):
            state, cls = "overgeslagen", "skip"
        else:
            state, cls = "gefaald", "bad"
        detail = s.get("skipped_reason") or s.get("error") or f"{s.get('items', 0)} items"
        rows.append(
            f'<tr><td>{esc(name)}</td><td class="st st-{cls}">{state}</td>'
            f'<td class="st-detail">{esc(str(detail)[:120])}</td></tr>'
        )
    return f"""
    <details class="sources">
      <summary>Bronstatus van vannacht</summary>
      <table>
        <thead><tr><th>Bron</th><th>Status</th><th>Details</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </details>"""


def _css_vars(d: dict) -> str:
    return "".join(f"--{k}:{v};" for k, v in d.items())


def render(model: dict) -> str:
    date_str = model.get("date", "")
    try:
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        pretty = date_str

    headline = model.get("headline") or "Geen bijzonderheden vandaag."
    tracks_html = "".join(
        render_track(key, title, window, blurb, model) for key, title, window, blurb in TRACKS
    )

    counts = model.get("counts") or {}
    summary_bits = []
    if counts.get("bevestigd"):
        summary_bits.append(f"{counts['bevestigd']} bevestigd")
    if counts.get("misschien"):
        summary_bits.append(f"{counts['misschien']} in de gaten")
    if counts.get("nieuw"):
        summary_bits.append(f"{counts['nieuw']} nieuw")
    sub = " &middot; ".join(summary_bits) or "niets in beeld"

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrendRadar {esc(pretty)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  .viz-root {{ {_css_vars(LIGHT)} }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{ {_css_vars(DARK)} }}
  }}
  :root[data-theme="dark"] .viz-root {{ {_css_vars(DARK)} }}

  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--primary);
  }}
  .viz-root {{ background: var(--page); min-height: 100vh; padding: 28px 20px 56px; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}

  header.top {{ margin-bottom: 28px; }}
  .eyebrow {{
    font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
    color: var(--muted); margin: 0 0 6px;
  }}
  h1 {{ font-size: 30px; line-height: 1.15; margin: 0 0 10px; font-weight: 600; }}
  .headline {{ font-size: 17px; line-height: 1.5; color: var(--secondary); margin: 0 0 6px; max-width: 68ch; }}
  .counts {{ font-size: 13px; color: var(--muted); margin: 0; }}

  .track {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 20px; margin-bottom: 18px;
  }}
  .track-head {{ margin-bottom: 14px; }}
  .track-title {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
  .track h2 {{ font-size: 19px; margin: 0 0 3px; font-weight: 600; }}
  .track-count {{ font-size: 12.5px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .blurb {{ font-size: 13px; color: var(--muted); margin: 0; }}

  .tiles {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(272px, 1fr)); }}
  .tile {{ border: 1px solid var(--border); border-radius: 11px; padding: 14px; background: var(--surface); }}
  .tile-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }}
  .tile h3 {{ font-size: 15px; margin: 0; font-weight: 600; line-height: 1.3; }}
  .score {{ font-size: 27px; font-weight: 600; line-height: 1; }}
  .tile-chart {{ margin: 10px 0 4px; }}
  .spark {{ display: block; overflow: visible; }}
  .spark-empty {{ font-size: 11px; fill: var(--muted); font-family: inherit; }}

  .delta {{ font-size: 13px; margin: 2px 0 0; font-weight: 500; }}
  .delta-up {{ color: var(--secondary); }}
  .delta-down {{ color: var(--secondary); }}
  .delta-flat {{ color: var(--muted); }}
  .why {{ font-size: 13px; line-height: 1.45; color: var(--secondary); margin: 8px 0 0; }}
  .meta {{ font-size: 11.5px; color: var(--muted); margin: 8px 0 0; }}

  .sub {{ font-size: 13px; text-transform: uppercase; letter-spacing: .07em;
         color: var(--muted); margin: 20px 0 8px; font-weight: 600; }}
  ul.maybe {{ list-style: none; margin: 0; padding: 0; }}
  ul.maybe li {{
    display: grid; grid-template-columns: minmax(120px, 1fr) 44px 2fr;
    gap: 10px; align-items: baseline;
    padding: 8px 0; border-top: 1px solid var(--grid); font-size: 13.5px;
  }}
  .maybe-name {{ font-weight: 500; }}
  .maybe-score {{ color: var(--secondary); font-variant-numeric: tabular-nums; text-align: right; }}
  .maybe-why {{ color: var(--muted); line-height: 1.4; }}

  .empty {{ font-size: 14px; color: var(--muted); margin: 4px 0; }}
  .dropped {{ font-size: 12.5px; color: var(--muted); margin: 16px 0 0;
             padding-top: 10px; border-top: 1px solid var(--grid); }}

  .sources {{ margin-top: 22px; font-size: 13px; }}
  .sources summary {{ cursor: pointer; color: var(--muted); }}
  .sources table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  .sources th {{ text-align: left; font-size: 11px; text-transform: uppercase;
                letter-spacing: .06em; color: var(--muted); font-weight: 600;
                padding: 5px 8px 5px 0; border-bottom: 1px solid var(--grid); }}
  .sources td {{ padding: 5px 8px 5px 0; border-bottom: 1px solid var(--grid); vertical-align: top; }}
  .st {{ font-weight: 600; white-space: nowrap; }}
  .st-ok {{ color: var(--secondary); }}
  .st-skip {{ color: var(--muted); }}
  .st-bad {{ color: var(--down); }}
  .st-detail {{ color: var(--muted); font-size: 12px; }}

  footer.bot {{ margin-top: 26px; font-size: 12px; color: var(--muted); line-height: 1.6; }}

  @media (max-width: 560px) {{
    .tiles {{ grid-template-columns: 1fr; }}
    ul.maybe li {{ grid-template-columns: 1fr 44px; }}
    .maybe-why {{ grid-column: 1 / -1; }}
    h1 {{ font-size: 25px; }}
  }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <header class="top">
      <p class="eyebrow">TrendRadar</p>
      <h1>{esc(pretty)}</h1>
      <p class="headline">{esc(headline)}</p>
      <p class="counts">{sub}</p>
    </header>
    {tracks_html}
    {render_sources(model)}
    <footer class="bot">
      Score 0&ndash;100 per dag: 60% versnelling t.o.v. het eigen gemiddelde,
      30% hoeveel onafhankelijke bronnen tegelijk stijgen, 10% niveau t.o.v. de eigen piek.
      Een eigen maat, puur om het verloop te kunnen zien.<br>
      Gegenereerd {esc(model.get('generated_at', ''))}.
    </footer>
  </div>
</div>
</body>
</html>"""


def main() -> int:
    if len(sys.argv) < 3:
        print("gebruik: render_report.py <model.json> <uitvoer.html>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        model = json.load(f)
    out = render(model)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(out)
    print(f"geschreven: {sys.argv[2]} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
