"""Parent report: one self-contained HTML page with each kid's reading progress.

    python -m word_punch.report          (writes reports/word_punch_report.html and opens it)
Also opened from the start screen: Players (P) -> R.
"""
from __future__ import annotations

import html
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT
from .profiles import Profile, ProfileStore
from .words import WordBank, norm

REPORTS = ROOT / "reports"


def word_status(s: dict | None) -> str:
    """strong | learning | trouble | new"""
    if not s or (s.get("read", 0) + s.get("missed", 0)) == 0:
        return "new"
    read, missed = s.get("read", 0), s.get("missed", 0)
    avg = s.get("time", 0) / read if read else 99
    if missed >= 2 and missed >= read / 2:
        return "trouble"
    if read >= 3 and avg <= 4.0 and missed <= read / 3:
        return "strong"
    return "learning"


def _stats_for(prof: Profile, text: str, is_letter: bool) -> dict | None:
    if is_letter:  # letters: combine "B" and "b"
        keys = [k for k in prof.word_stats if norm(k) == norm(text)]
        if not keys:
            return None
        out = {"seen": 0, "read": 0, "missed": 0, "time": 0.0}
        for k in keys:
            for f in out:
                out[f] += prof.word_stats[k].get(f, 0)
        return out
    return prof.word_stats.get(text)


def _activity_svg(prof: Profile, days: int = 14) -> str:
    today = date.today()
    counts = {}
    for h in prof.history:
        d = h.get("date", "")[:10]
        counts[d] = counts.get(d, 0) + h.get("words", 0)
    series = [(today - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    vals = [counts.get(d.isoformat(), 0) for d in series]
    top = max(vals + [10])
    w, h, gap = 26, 90, 6
    bars = []
    for i, (d, v) in enumerate(zip(series, vals)):
        bh = int(h * v / top)
        x = i * (w + gap)
        bars.append(f'<rect x="{x}" y="{h - bh}" width="{w}" height="{max(bh, 1)}" rx="4" class="bar{" zero" if not v else ""}">'
                    f'<title>{d:%a %b %d}: {v} words</title></rect>')
        if v:
            bars.append(f'<text x="{x + w / 2}" y="{h - bh - 4}" class="val">{v}</text>')
        bars.append(f'<text x="{x + w / 2}" y="{h + 14}" class="day">{d.strftime("%a")[0]}</text>')
    width = days * (w + gap)
    return f'<svg viewBox="0 -14 {width} {h + 30}" class="chart" role="img" aria-label="Words read per day">{"".join(bars)}</svg>'


def kid_section(prof: Profile, bank: WordBank) -> str:
    e = html.escape
    cur = bank.level(prof.level)
    # level path
    chips = []
    for key in bank.order:
        lvl = bank.level(key)
        if lvl.index < cur.index:
            cls, label = "done", "&#10003;"
        elif key == prof.level:
            need = 2
            keys = {norm(w) if lvl.is_letters else w for w in lvl.words}
            got = sum(min(prof.good.get(k, 0), need) for k in keys)
            pct = int(100 * got / (need * len(keys))) if keys else 0
            cls, label = "current", f"{pct}%"
        else:
            cls, label = "todo", ""
        chips.append(f'<div class="chip {cls}"><span>{e(lvl.name)}</span><b>{label}</b></div>')

    # word grid: current level + all earlier levels
    grids = []
    for key in bank.order[: cur.index + 1][::-1]:
        lvl = bank.level(key)
        words = lvl.words
        played = any(_stats_for(prof, w, lvl.is_letters) for w in words)
        if key != prof.level and not played:
            continue  # an earlier level this kid never played (e.g. letters for a reader)
        if lvl.is_letters:
            words = [w for w in words if w.isupper()]  # one cell per letter
        cells = []
        for w in words:
            s = _stats_for(prof, w, lvl.is_letters)
            st = word_status(s)
            tip = "not seen yet" if not s else (f"read {s['read']}x, missed {s['missed']}x"
                                               + (f", avg {s['time'] / s['read']:.1f}s" if s.get("read") else ""))
            shown = f"{w}{w.lower()}" if lvl.is_letters else w
            cells.append(f'<span class="w {st}" title="{e(tip)}">{e(shown)}</span>')
        grids.append(f'<h4>{e(lvl.name)}</h4><div class="grid">{"".join(cells)}</div>')

    # trouble words
    merged: dict[str, dict] = {}
    letters = set(bank.level("letters").words) if "letters" in bank.levels else set()
    for w, st in prof.word_stats.items():
        key = w.upper() if (w in letters and prof.level == "letters") else w  # B + b together
        m = merged.setdefault(key, {"seen": 0, "read": 0, "missed": 0, "time": 0.0})
        for f in m:
            m[f] += st.get(f, 0)
    trouble = sorted(((w, s) for w, s in merged.items() if word_status(s) == "trouble"),
                     key=lambda x: (-x[1]["missed"], x[1]["read"]))[:10]
    trouble_html = "".join(f'<li><b>{e(w)}</b> missed {s["missed"]}x, read {s["read"]}x</li>' for w, s in trouble) \
        or "<li class='muted'>None right now - nice!</li>"

    # sessions
    rows = []
    for h in prof.history[::-1][:15]:
        game = h.get("game", "classic").replace("classic", "word punch")
        res = {"complete": "&#11088; complete", "out": "out of lives"}.get(h.get("result", ""), h.get("result", ""))
        rows.append(f"<tr><td>{e(h.get('date', ''))}</td><td>{e(game)}</td><td>{e(h.get('mode', ''))} / "
                    f"{e(h.get('style', 'punch'))}</td><td>{h.get('words', 0)}</td><td>{h.get('misses', 0)}</td>"
                    f"<td>{h.get('score', 0)}</td><td>{h.get('minutes', '')}</td><td>{res}</td></tr>")
    sessions = "".join(rows) or "<tr><td colspan=8 class='muted'>No rounds finished yet</td></tr>"

    seen = [s for s in prof.word_stats.values() if s.get("read")]
    total_time = sum(s["time"] for s in seen)
    total_reads = sum(s["read"] for s in seen)
    avg = f"{total_time / total_reads:.1f}s" if total_reads else "-"
    strong = sum(1 for s in prof.word_stats.values() if word_status(s) == "strong")
    stars = getattr(prof, "stars", 0)
    minutes = sum(h.get("minutes", 0) or 0 for h in prof.history)
    reached = ", ".join(f"{bank.level(k).name} ({d})" for k, d in prof.levels_reached.items() if k in bank.levels)

    return f"""
<section class="kid">
  <header><h2>{e(prof.name)}</h2><div class="level">Working on <b>{e(cur.name)}</b></div></header>
  <div class="stats">
    <div><b>{prof.words_read}</b><span>words read</span></div>
    <div><b>{strong}</b><span>strong words</span></div>
    <div><b>{avg}</b><span>avg time to read</span></div>
    <div><b>{prof.sessions}</b><span>rounds</span></div>
    <div><b>{minutes:.0f}</b><span>minutes played</span></div>
    <div><b>{stars}</b><span>stars</span></div>
  </div>
  <div class="path">{"".join(chips)}</div>
  <div class="cols">
    <div><h3>Words</h3>
      <div class="legend"><span class="w strong">strong</span><span class="w learning">learning</span>
      <span class="w trouble">trouble</span><span class="w new">not seen</span></div>
      {"".join(grids)}</div>
    <div><h3>Trouble words</h3><ul class="trouble">{trouble_html}</ul>
      <h3>Last 2 weeks</h3>{_activity_svg(prof)}
      <p class="muted small">Levels reached: {e(reached) or "-"}</p></div>
  </div>
  <h3>Recent rounds</h3>
  <table><thead><tr><th>When</th><th>Game</th><th>Mode</th><th>Words</th><th>Misses</th><th>Score</th>
  <th>Min</th><th>Result</th></tr></thead><tbody>{sessions}</tbody></table>
</section>"""


CSS = """
:root{--ink:#1d2433;--muted:#6b7385;--line:#e3e6ee;--bg:#f6f7fb;--card:#fff;--gold:#f5b800;
--strong:#2e9d57;--learning:#3a7bd5;--trouble:#d64545;--new:#b8bdc9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 "Andika","Segoe UI",system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 48px}
h1{margin:0 0 4px;font-size:28px}.sub{color:var(--muted);margin:0 0 20px}
.kid{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin:0 0 24px}
.kid header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;justify-content:space-between}
h2{margin:0;font-size:24px}h3{margin:18px 0 8px;font-size:16px}h4{margin:10px 0 6px;font-size:13px;color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:14px 0}
.stats div{background:var(--bg);border-radius:10px;padding:10px;text-align:center}
.stats b{display:block;font-size:22px}.stats span{color:var(--muted);font-size:12px}
.path{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 4px}
.chip{border:1px solid var(--line);border-radius:999px;padding:4px 10px;font-size:12px;display:flex;gap:6px}
.chip.done{background:#e7f6ec;border-color:#bfe5cc}.chip.current{background:#fff6d6;border-color:var(--gold);font-weight:bold}
.chip.todo{color:var(--muted)}
.cols{display:grid;grid-template-columns:2fr 1fr;gap:24px}
@media (max-width:720px){.cols{grid-template-columns:1fr}}
.grid{display:flex;flex-wrap:wrap;gap:5px}
.w{display:inline-block;padding:3px 8px;border-radius:6px;font-weight:bold;color:#fff;font-size:14px}
.w.strong{background:var(--strong)}.w.learning{background:var(--learning)}.w.trouble{background:var(--trouble)}
.w.new{background:#eef0f4;color:var(--new)}
.legend{display:flex;gap:6px;margin-bottom:4px}.legend .w{font-size:11px;font-weight:normal}
.trouble{padding-left:18px;margin:0}.muted{color:var(--muted)}.small{font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:normal}
.chart{width:100%;max-width:460px;height:auto}.chart .bar{fill:var(--learning)}.chart .bar.zero{fill:var(--line)}
.chart .val{font-size:9px;text-anchor:middle;fill:var(--ink)}.chart .day{font-size:9px;text-anchor:middle;fill:var(--muted)}
@media print{body{background:#fff}.kid{break-inside:avoid;border-color:#ccc}}
"""


def build(profiles: list[Profile], bank: WordBank) -> str:
    kids = "".join(kid_section(p, bank) for p in sorted(profiles, key=lambda p: p.name.lower())) \
        or "<p>No players yet.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Word Punch progress</title>
<style>{CSS}</style></head><body><main>
<h1>Word Punch - reading progress</h1>
<p class="sub">Updated {time.strftime("%B %d, %Y %I:%M %p")}. Hover a word to see how often it was read or missed.</p>
{kids}</main></body></html>"""


def write_report(open_browser: bool = True) -> Path:
    bank = WordBank()
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / "word_punch_report.html"
    path.write_text(build(ProfileStore().all(), bank), encoding="utf-8")
    if open_browser:
        webbrowser.open(path.as_uri())
    return path


if __name__ == "__main__":
    print(write_report())
