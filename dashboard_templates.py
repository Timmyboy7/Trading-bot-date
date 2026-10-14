"""Jinja templates for dashboard.py (autoescaped; no JavaScript)."""

CSS = """
:root{--ink:#0E1A2B;--ink2:#22324A;--muted:#4A5568;--line:#DDE3EA;--soft:#EEF1F5;--bg:#F3F5F7;--card:#FFFFFF;
--teal:#0B6E66;--teal-bg:#E6F2F0;--teal-ink:#0B4F49;--warn:#B4460F;--warn-bg:#FBEDE4;--warn-ink:#8A3A0C;--grey:#7D8899}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:'Public Sans',system-ui,sans-serif;font-size:15px}
body.large{font-size:18px}a{color:var(--teal)}a:hover{color:#08524C}
.mono{font-family:'IBM Plex Mono',ui-monospace,monospace}
header.top{background:var(--ink);color:#fff}.top .in{max-width:1180px;margin:0 auto;padding:0 24px;min-height:64px;display:flex;flex-wrap:wrap;align-items:center;gap:12px 28px}
.brand{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;font-weight:700;font-size:18px}
nav.main{display:flex;flex-wrap:wrap;gap:2px;flex:1 1 auto}nav.main a{color:#C9D2DE;text-decoration:none;font-weight:500;padding:12px 12px;border-bottom:3px solid transparent}
nav.main a.on{color:#fff;font-weight:600;border-bottom-color:#5FD3C6}.who{display:flex;align-items:center;gap:12px;font-size:14px}
.who a{color:#C9D2DE}.pill{background:#23344D;color:#fff;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600}
main{max-width:1180px;margin:0 auto;padding:32px 24px 56px;display:flex;flex-direction:column;gap:24px}
h1{margin:0;font-size:28px}h2{margin:0;font-size:18px}.sub{margin:6px 0 0;color:var(--muted);line-height:1.5}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px}.row{display:flex;flex-wrap:wrap;gap:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.tile .k{font-size:13px;color:var(--muted)}.tile .v{font-size:18px;font-weight:700;margin-top:6px}.tile .s{font-size:13px;color:var(--muted);margin-top:4px}
.big{font-size:44px;font-weight:600;margin-top:4px}.pos{color:var(--teal)}.neg{color:var(--warn)}
.note{background:var(--teal-bg);border-radius:10px;padding:16px 18px}.warnbox{background:#FFF4D6;color:#4D3A00;border-radius:12px;padding:14px 18px}
.tag{display:inline-block;min-width:64px;text-align:center;font-size:12px;font-weight:700;border-radius:6px;padding:4px 6px}
.t-BUY{background:var(--teal-bg);color:var(--teal-ink)}.t-SELL{background:var(--warn-bg);color:var(--warn-ink)}.t-WAIT,.t-CHECK{background:var(--soft);color:#33475B}.t-ALARM{background:#FFF4D6;color:#6B4E00}
.badge{font-size:12px;font-weight:600;padding:3px 9px;border-radius:999px;white-space:nowrap}.b-ok{background:var(--teal-bg);color:var(--teal-ink)}.b-warn{background:var(--warn-bg);color:var(--warn-ink)}.b-grey{background:var(--soft);color:#33475B}
.list>div,.list>li{padding:14px 0;border-top:1px solid var(--soft)}.list{list-style:none;margin:12px 0 0;padding:0}
.item{display:flex;gap:14px}.item .why{font-size:14px;color:var(--muted);margin-top:3px;line-height:1.5}
.bar{height:6px;background:var(--soft);border-radius:3px}.bar>div{height:6px;border-radius:3px;background:var(--teal)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 12px;text-align:left;vertical-align:middle}thead tr{background:#F7F9FB;color:var(--muted)}
tbody tr{border-top:1px solid var(--soft)}td.r,th.r{text-align:right}.scroll{overflow-x:auto}.tbl{padding:0;overflow:hidden}
.legend{display:flex;flex-wrap:wrap;gap:8px 22px;font-size:13px;color:#33475B}.legend span{display:flex;align-items:center;gap:8px}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chips a{min-height:44px;display:inline-flex;align-items:center;padding:0 16px;border-radius:999px;border:1px solid #CBD3DD;background:#fff;color:var(--ink2);text-decoration:none;font-weight:600;font-size:14px}
.chips a.on{background:var(--ink);border-color:var(--ink);color:#fff}
.dl{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;padding:16px 0;border-top:1px solid var(--soft)}.dl .d{flex:1 1 380px;min-width:0}
.btn{display:inline-block;font-weight:600;padding:10px 16px;border:1px solid var(--teal);border-radius:8px;text-decoration:none;min-height:44px}
form.stack{display:flex;flex-direction:column;gap:18px}label{font-weight:600}input[type=text],input[type=password]{font:inherit;font-size:16px;padding:12px 14px;min-height:46px;border:1px solid #B8C2CF;border-radius:8px;width:100%}
button.primary{font:inherit;font-size:16px;font-weight:600;min-height:48px;border:0;border-radius:10px;background:var(--teal);color:#fff;cursor:pointer}
.opt{display:flex;gap:10px;flex-wrap:wrap}.opt label{display:flex;align-items:center;gap:8px;border:2px solid #CBD3DD;border-radius:10px;padding:10px 16px;font-weight:600;cursor:pointer}
.prose{font-size:16px;line-height:1.65;color:var(--ink2)}.prose h2{font-size:22px;color:var(--ink);margin-bottom:10px}.prose p{margin:0 0 10px}.prose ul{margin:0;padding-left:22px}.prose li{margin-bottom:8px}
.err{font-size:13px;color:var(--warn-ink)}
@media (max-width:640px){main{padding:20px 16px 40px}.big{font-size:34px}.top .in{padding:0 16px}nav.main a{padding:10px 8px}}
"""

BASE = """<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ t(page) ~ ' — ' if page else '' }}Wunschik Capital</title><meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>""" + CSS + """</style></head><body class="{{ 'large' if me and me.large else '' }}">
<header class="top"><div class="in">
<a class="brand" href="/app/"><svg width="24" height="24" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="11" fill="#5FD3C6"/><text x="11" y="15.4" text-anchor="middle" font-family="Public Sans, sans-serif" font-size="12.5" font-weight="700" fill="#0E1A2B">W</text></svg>Wunschik Capital</a>
<nav class="main" aria-label="Main">{% for k, href in nav %}<a href="{{ href }}" class="{{ 'on' if page == k else '' }}">{{ t(k) }}</a>{% endfor %}</nav>
<div class="who">{% if me.owner %}<span class="pill">{{ t('owner') }}</span>{% endif %}<a href="/app/profile" style="color:#E3E8EF;text-decoration:none">{{ me.name }}</a><a href="/app/logout">{{ t('sign_out') }}</a></div>
</div></header>
<main>{% block body %}{% endblock %}</main></body></html>"""

LOGIN = """<!doctype html><html lang="{{ lang }}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wunschik Capital — {{ t('sign_in') }}</title><meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet"><style>""" + CSS + """
body{background:var(--ink);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px}
.box{width:100%;max-width:400px;background:#fff;border-radius:16px;padding:36px 32px}</style></head><body>
<form class="box stack" method="post" action="/app/login?lang={{ lang }}">
<div class="brand" style="color:var(--ink)"><svg width="26" height="26" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="11" fill="#0B6E66"/><text x="11" y="15.4" text-anchor="middle" font-family="Public Sans, sans-serif" font-size="12.5" font-weight="700" fill="#FFFFFF">W</text></svg>Wunschik Capital</div>
<div><h1 style="font-size:22px">{{ t('sign_in') }}</h1><p class="sub">{{ t('private') }}</p></div>
{% if msg %}<p class="err" role="alert">{{ t(msg) }}</p>{% endif %}
{% if not configured %}<p class="err">No users configured yet (DASH_USERS on Render).</p>{% endif %}
<input type="hidden" name="csrf" value="{{ csrf }}">
<div class="stack" style="gap:6px"><label for="u">{{ t('username') }}</label><input id="u" name="username" type="text" autocomplete="username" autocapitalize="none" required></div>
<div class="stack" style="gap:6px"><label for="p">{{ t('password') }}</label><input id="p" name="password" type="password" autocomplete="current-password" required></div>
<button class="primary" type="submit">{{ t('sign_in') }}</button>
<p class="sub" style="font-size:13px">{{ t('login_note') }} · <a href="/app/login?lang={{ 'de' if lang == 'en' else 'en' }}">{{ 'Deutsch' if lang == 'en' else 'English' }}</a></p>
</form></body></html>"""

OVERVIEW = """{% extends 'base.html' %}{% block body %}
<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px">
<h1>{{ t(greet) }}, {{ me.name }}</h1><p class="sub" style="margin:0">{{ t('paper_note') }}</p></div>
{% if err %}<div class="warnbox">{{ t('data_issue') }}: <span class="mono" style="font-size:12px">{{ err }}</span></div>{% endif %}
{% if p %}
<section class="card row" aria-label="Performance" style="padding:28px;gap:32px">
<div style="flex:1 1 300px;display:flex;flex-direction:column;gap:20px;min-width:0">
<div><div class="k" style="color:var(--muted);font-weight:500">{{ t('value') }}</div>
<div class="big mono">{{ money(eq) }}</div>
<div style="margin-top:6px"><span class="{{ 'pos' if gain >= 0 else 'neg' }}" style="font-weight:600">{{ money(gain, sign=True) }} ({{ pct(gain_pct) }})</span> <span style="color:var(--muted)">{{ t('on') }} {{ money(p.paid_in, dec=0) }} {{ t('paid_in') }}</span></div></div>
{% if spy_value %}<div class="note"><div style="font-size:13px;color:var(--teal-ink);font-weight:600;text-transform:uppercase;letter-spacing:.06em">{{ t('vs_spy') }}</div>
<div style="font-size:20px;font-weight:700;margin-top:6px">{{ t('ahead') if excess >= 0 else t('behind') }} {{ money(excess|abs, dec=2) }}</div>
<div style="font-size:14px;color:#33475B;margin-top:4px;line-height:1.45">{{ t('spy_same') }} {{ money(spy_value) }}.</div></div>{% endif %}
<dl style="margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 20px;font-size:14px">
<div><dt style="color:var(--muted)">{{ t('started') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ date(p.start) if p.start else '—' }}</dd></div>
<div><dt style="color:var(--muted)">{{ t('monthly') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ money(p.deposits[1][1] if p.deposits|length > 1 else 100, dec=0) }}</dd></div>
<div><dt style="color:var(--muted)">{{ t('held') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ n_held }} {{ t('of') }} {{ basket_n }}</dd></div>
<div><dt style="color:var(--muted)">{{ t('cash') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ pct(cash_pct, sign=False) }}</dd></div></dl></div>
<figure style="flex:2 1 520px;margin:0;min-width:0;display:flex;flex-direction:column;gap:12px">
<figcaption style="font-weight:600">{{ t('since_start') }}</figcaption>
{% if chart %}<svg viewBox="-8 -12 {{ chart.w + 16 }} {{ chart.h + 30 }}" style="width:100%;height:auto;display:block" role="img" aria-label="{{ t('since_start') }}">
{% for y, v in chart.grid %}<line x1="0" y1="{{ y }}" x2="{{ chart.w }}" y2="{{ y }}" stroke="#E8ECF1"/><text x="{{ chart.w }}" y="{{ y - 4 }}" text-anchor="end" font-size="11" fill="#4A5568">{{ money(v, dec=0) }}</text>{% endfor %}
<polyline fill="none" stroke="#A9B3C1" stroke-width="1.5" stroke-dasharray="4 4" points="{{ chart.paid }}"/>
<polyline fill="none" stroke="#7D8899" stroke-width="2.5" points="{{ chart.spy }}"/>
<polyline fill="none" stroke="#0B6E66" stroke-width="3" points="{{ chart.basket }}"/>
<circle cx="{{ chart.end[0] }}" cy="{{ chart.end[1] }}" r="5" fill="#0B6E66"/>
<text x="0" y="{{ chart.h + 16 }}" font-size="11" fill="#4A5568">{{ date(chart.first) }}</text><text x="{{ chart.w }}" y="{{ chart.h + 16 }}" font-size="11" fill="#4A5568" text-anchor="end">{{ date(chart.last) }}</text></svg>
<div class="legend"><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#0B6E66" stroke-width="3"/></svg>{{ t('your_basket') }}</span>
<span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#7D8899" stroke-width="2.5"/></svg>{{ t('spy_line') }}</span>
<span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#A9B3C1" stroke-width="1.5" stroke-dasharray="4 4"/></svg>{{ t('paid_in')|capitalize }}</span></div>
{% else %}<p class="sub">{{ t('chart_wait') if n_held else t('nothing_yet') }}</p>{% endif %}</figure></section>
{% endif %}
<div class="grid">
<div class="tile"><div class="k">{{ t('next_decision') }}</div><div class="v">20:00</div><div class="s">{{ t('daily_check') }}</div></div>
<div class="tile"><div class="k">{{ t('alarm') }}</div><div class="v">ON</div><div class="s">{{ t('alarm_text') }}</div></div>
<div class="tile"><div class="k">{{ t('tax_hold') }}</div><div class="v">{{ in_hold or 0 }} {{ t('stocks') }}</div><div class="s">{% if first_free %}{{ t('tax_free_from') }} {{ date(first_free) }}{% else %}—{% endif %}</div></div>
<div class="tile"><div class="k">{{ t('next_review') }}</div><div class="v">{{ t('sunday') }}</div><div class="s">{{ t('picks20') }}</div></div></div>
{% if risk %}<section class="card row" style="align-items:center;gap:16px 28px" aria-labelledby="hl">
<div style="flex:1 1 260px;display:flex;align-items:center;gap:16px"><svg width="56" height="56" viewBox="0 0 96 96" aria-hidden="true"><circle cx="48" cy="48" r="40" fill="none" stroke="#EEF1F5" stroke-width="12"/><circle cx="48" cy="48" r="40" fill="none" stroke="#0B6E66" stroke-width="12" stroke-dasharray="{{ (risk.ok / 4 * 251)|round(1) }} 251" stroke-linecap="round" transform="rotate(-90 48 48)"/></svg>
<div><h2 id="hl">{{ t('health') }}</h2><div class="sub">{{ t('checks_green', a=risk.ok, b=4) }}</div></div></div>
<div style="flex:2 1 480px;display:flex;flex-wrap:wrap;gap:10px">{% for s in risk.scen[:3] %}<span style="font-size:13px;padding:8px 12px;border-radius:8px;background:{{ '#FBEDE4' if s.status != 'within' else '#F7F9FB' }}">{{ s.label[1] if lang == 'de' else s.label[0] }} → <strong class="mono">{{ pct(s.basket) }}</strong></span>{% endfor %}<a href="/app/risk" style="font-weight:600;padding:8px 4px">{{ t('risk') }} →</a></div></section>{% endif %}
<div class="row">
<section class="card" style="flex:3 1 480px;min-width:0" aria-labelledby="wk"><div style="display:flex;justify-content:space-between;gap:12px"><h2 id="wk">{{ t('this_week') }}</h2><a href="/app/activity" style="font-weight:600">{{ t('all_activity') }}</a></div>
{% if week %}<ul class="list">{% for i in week %}<li class="item"><span class="tag t-{{ i.tag }}" style="height:fit-content">{{ tag(i.tag) }}</span><div><div style="font-weight:600">{{ i.title }}{% if i.test %} <span class="badge b-grey">{{ t('test_run') }}</span>{% endif %}</div><div class="why mono" style="font-size:12px">{{ i.why }}</div></div></li>{% endfor %}</ul>
{% else %}<p class="sub">{{ t('no_activity') }}</p>{% endif %}</section>
<section class="card" style="flex:2 1 320px;min-width:0" aria-labelledby="bg"><div style="display:flex;justify-content:space-between;gap:12px"><h2 id="bg">{{ t('biggest') }}</h2><a href="/app/holdings" style="font-weight:600">{{ t('all_holdings') }}</a></div>
{% if rows %}<div class="list">{% for r in rows %}<div><div style="display:flex;justify-content:space-between;font-size:14px"><span><strong class="mono">{{ r.symbol }}</strong></span><span class="mono">{{ pct(r.share, sign=False) }}</span></div><div class="bar" style="margin-top:6px"><div style="width:{{ [r.share * 10, 100]|min }}%"></div></div></div>{% endfor %}</div>
{% else %}<p class="sub">{{ t('nothing_yet') }}</p>{% endif %}</section></div>
{% endblock %}"""

HOLDINGS = """{% extends 'base.html' %}{% block body %}
<div><h1>{{ t('holdings') }}</h1><p class="sub">{% if p %}{{ rows|length }} {{ t('stocks') }} · {{ t('cash') }} {{ money(p.account.cash|float) }}. {% endif %}{{ t('click_stock') }}</p></div>
{% if err %}<div class="warnbox">{{ t('data_issue') }}: <span class="mono" style="font-size:12px">{{ err }}</span></div>{% endif %}
{% if rows %}<section class="card tbl"><div class="scroll"><table style="min-width:820px"><thead><tr>
<th scope="col" style="padding-left:20px">{{ t('stock') }}</th><th class="r" scope="col">{{ t('value') }}</th><th class="r" scope="col">{{ t('share') }}</th><th class="r" scope="col">{{ t('gain') }}</th><th scope="col">{{ t('tax_hold') }}</th><th scope="col">{{ t('trend') }}</th><th scope="col">{{ t('next_event') }}</th></tr></thead><tbody>
{% for r in rows %}<tr style="{{ 'background:#F1F8F7' if sel and sel.symbol == r.symbol else '' }}"><th scope="row" style="padding-left:20px;font-weight:400"><a href="/app/holdings?s={{ r.symbol }}" style="font-weight:600;color:var(--ink)">{{ nm(r.symbol) or r.symbol }}</a>{% if nm(r.symbol) %} <span class="mono" style="font-size:12px;color:var(--muted)">{{ r.symbol }}</span>{% endif %}</th>
<td class="r mono">{{ money(r.value) }}</td><td class="r mono">{{ pct(r.share, sign=False) }}</td><td class="r mono {{ 'pos' if r.gain >= 0 else 'neg' }}" style="font-weight:600">{{ pct(r.gain) }}</td>
<td style="min-width:150px"><div style="font-size:12px;color:var(--muted)">{{ t('day_of', d=r.day) }}</div><div class="bar" style="margin-top:5px"><div style="width:{{ r.hold_pct }}%;background:#4C6A8A"></div></div></td>
<td><span class="badge {{ 'b-ok' if r.state == 'healthy' else 'b-warn' }}">{{ t(r.state) }}</span></td><td>{% if r.next %}{{ t('results') }} {{ date(r.next) }}{% else %}—{% endif %}</td></tr>{% endfor %}
</tbody></table></div></section>
{% if sel %}<section class="card" style="padding:28px;display:flex;flex-direction:column;gap:22px" aria-labelledby="sc">
<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px"><div><h2 id="sc" style="font-size:24px">{{ nm(sel.symbol) or sel.symbol }}{% if nm(sel.symbol) %} <span class="mono" style="font-size:15px;color:var(--muted)">{{ sel.symbol }}</span>{% endif %}{% if sel.cluster %} · <span style="font-weight:500">{{ sel.cluster|replace('_', ' ') }}</span>{% endif %}</h2>
<p class="sub">{{ t('started') }} {{ date(sel.since) }}</p></div>
<div style="display:flex;gap:24px;flex-wrap:wrap"><div><div class="sub" style="margin:0;font-size:13px">{{ t('value') }}</div><div class="mono" style="font-size:20px;font-weight:600">{{ money(sel.value) }}</div></div>
<div><div class="sub" style="margin:0;font-size:13px">{{ t('gain') }}</div><div class="mono {{ 'pos' if sel.gain >= 0 else 'neg' }}" style="font-size:20px;font-weight:600">{{ pct(sel.gain) }}</div></div></div></div>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px">
<div class="prose" style="font-size:15px"><h2 style="font-size:16px">{{ t('why_own') }}</h2><p>{{ sel.thesis or '—' }}</p>
<h2 style="font-size:16px;margin-top:14px">{{ t('sell_if') }}</h2>{% if sel.kill %}<ul>{% for k in sel.kill %}<li>{{ k }}</li>{% endfor %}</ul>{% else %}<p>—</p>{% endif %}
<p class="sub" style="font-size:13px">{{ t('checked_daily') }}</p><p><a href="/app/stock/{{ sel.symbol }}">{{ t('full_research') }} →</a></p></div>
<div style="display:flex;flex-direction:column;gap:10px;font-size:14px"><h2 style="font-size:16px">{{ t('rules_now') }}</h2>
<div class="tile" style="display:flex;justify-content:space-between;padding:12px 14px"><span>{{ t('above_avg') }}</span><strong class="{{ 'pos' if sel.above else 'neg' }}">{{ t('yes') if sel.above else t('no') }}</strong></div>
<div class="tile" style="display:flex;justify-content:space-between;padding:12px 14px"><span>{{ t('below_high') }}</span><strong>{{ pct(sel.dd) if sel.dd is not none else '—' }} <span style="font-weight:400;color:var(--muted)">({{ t('sell_rule_25') }})</span></strong></div>
<div class="tile" style="display:flex;justify-content:space-between;padding:12px 14px"><span>{{ t('stop') }}</span><strong>−35% <span style="font-weight:400;color:var(--muted)">({{ t('now') }} {{ pct(sel.gain) }})</span></strong></div>
<div class="tile" style="display:flex;justify-content:space-between;padding:12px 14px"><span>{{ t('tax_free') }}</span><strong>{{ date(sel.tax_free) }}</strong></div>
{% if sel.catalysts %}<h2 style="font-size:16px;margin-top:6px">{{ t('coming_up') }}</h2><ul class="list" style="margin:0">{% for c in sel.catalysts %}<li style="padding:8px 0;display:flex;gap:12px"><span class="mono" style="color:var(--muted);min-width:90px">{{ date(c.date) }}</span><span>{{ c.event }}</span></li>{% endfor %}</ul>{% endif %}
</div></div></section>{% endif %}
{% else %}<div class="card"><p class="sub" style="margin:0">{{ t('nothing_yet') }}</p></div>{% endif %}
{% endblock %}"""

BASKET = """{% extends 'base.html' %}{% block body %}
<div><h1>{{ t('basket') }}</h1><p class="sub" style="max-width:760px">{{ t('basket_intro') }}</p>{% if m %}<p class="sub">{{ t('basket_of') }} {{ date(m.run_date[:10]) }}</p>{% endif %}</div>
{% if serr %}<div class="warnbox">{{ t(serr) }}</div>{% endif %}
{% if m %}<section class="card tbl" aria-labelledby="in"><div style="padding:22px 24px 10px;display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px"><h2 id="in">{{ t('in_basket') }} ({{ m.rows|length }})</h2><span class="sub" style="margin:0;font-size:13px">{{ t('score_note') }}</span></div>
<div class="scroll"><table style="min-width:900px"><thead><tr><th scope="col" style="padding-left:24px">{{ t('rank') }}</th><th scope="col">{{ t('stock') }}</th><th scope="col">{{ t('sector_theme') }}</th><th scope="col" style="width:170px">{{ t('score') }}</th><th class="r" scope="col">{{ t('target_share') }}</th><th scope="col">{{ t('note') }}</th></tr></thead><tbody>
{% for r in m.rows %}<tr><td class="mono" style="padding-left:24px;color:var(--muted)">{{ r.rank or '—' }}</td><th scope="row" style="font-weight:400"><a href="/app/stock/{{ r.symbol }}" style="font-weight:700;color:var(--ink)">{{ nm(r.symbol) or r.symbol }}</a>{% if nm(r.symbol) %} <span class="mono" style="font-size:12px;color:var(--muted)">{{ r.symbol }}</span>{% endif %}<div style="font-size:12px;color:var(--muted);max-width:340px">{{ r.thesis[:140] }}</div></th>
<td style="color:#33475B">{{ r.sector }}{% if r.theme %} · {{ r.theme }}{% endif %}</td><td><div style="display:flex;align-items:center;gap:10px"><div class="bar" style="flex:1 1 auto"><div style="width:{{ r.bar }}%"></div></div><span class="mono" style="font-size:13px">{{ '%.2f'|format(r.score) if r.score else '—' }}</span></div></td>
<td class="r mono">{{ pct(r.weight, sign=False) }}</td><td>{% if r.note %}<span class="badge {{ 'b-grey' if r.note == 'Filled a free place' else 'b-warn' }}">{{ r.note }}</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div></section>
<div class="row"><section class="card" style="flex:1 1 480px;min-width:0" aria-labelledby="con"><h2 id="con">{{ t('knocking') }}</h2><p class="sub" style="font-size:13px">{{ t('knocking_note') }}</p>
<div class="list">{% for c in m.contenders %}<div class="item"><span class="mono" style="flex:0 0 36px;color:var(--muted)">{{ c.rank }}</span><div style="flex:1 1 auto;min-width:0"><a href="/app/stock/{{ c.symbol }}" style="font-weight:700;color:var(--ink)">{{ nm(c.symbol) or c.symbol }}</a>{% if nm(c.symbol) %} <span class="mono" style="font-size:12px;color:var(--muted)">{{ c.symbol }}</span>{% endif %} <span style="color:var(--muted);font-size:13px">{{ c.sector }}</span><div class="why">{{ c.thesis[:160] }}</div></div><span class="badge {{ 'b-warn' if c.why in ('blk_red','blk_theme','blk_sector','blk_unc') else 'b-grey' }}" style="height:fit-content">{{ t(c.why) }}</span></div>{% else %}<p class="sub">—</p>{% endfor %}</div></section>
<section class="card" style="flex:1 1 480px;min-width:0" aria-labelledby="dr"><h2 id="dr">{{ t('dropping') }}</h2><p class="sub" style="font-size:13px">{{ t('dropping_note') }}</p>
<div class="list">{% for d in m.drops %}<div class="item"><span class="mono" style="flex:0 0 36px;color:var(--muted)">{{ d.rank or '—' }}</span><div><a href="/app/stock/{{ d.symbol }}" style="font-weight:700;color:var(--ink)">{{ nm(d.symbol) or d.symbol }}</a>{% if nm(d.symbol) %} <span class="mono" style="font-size:12px;color:var(--muted)">{{ d.symbol }}</span>{% endif %}{% if d.note %} <span class="badge b-warn">{{ d.note }}</span>{% endif %}<div class="why">{{ d.reason }}</div></div></div>{% endfor %}</div></section></div>
{% endif %}{% endblock %}"""

RISK = """{% extends 'base.html' %}{% block body %}
<div><h1>{{ t('health') }}</h1><p class="sub">{{ t('health_intro') }}{% if run_date %} · {{ date(run_date[:10]) }}{% endif %}</p></div>
{% if serr %}<div class="warnbox">{{ t(serr) }}</div>{% endif %}
{% if m %}<section class="card row" style="align-items:center;padding:28px;gap:28px" aria-label="{{ t('health') }}">
<div style="flex:1 1 240px;display:flex;align-items:center;gap:20px"><svg width="96" height="96" viewBox="0 0 96 96" role="img" aria-label="{{ t('checks_green', a=m.ok, b=4) }}"><circle cx="48" cy="48" r="40" fill="none" stroke="#EEF1F5" stroke-width="10"/><circle cx="48" cy="48" r="40" fill="none" stroke="#0B6E66" stroke-width="10" stroke-dasharray="{{ (m.ok / 4 * 251)|round(1) }} 251" stroke-linecap="round" transform="rotate(-90 48 48)"/><text x="48" y="55" text-anchor="middle" font-size="22" font-weight="600" fill="#0E1A2B">{{ m.ok }}/4</text></svg>
<div style="font-size:20px;font-weight:700">{{ t('checks_green', a=m.ok, b=4) }}</div></div>
<div class="grid" style="flex:2 1 520px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">{% for key, ok, detail in m.checks %}<div class="tile" style="display:flex;gap:12px;padding:14px 16px"><span style="flex:0 0 22px;height:22px;border-radius:11px;background:{{ '#0B6E66' if ok else '#B4460F' }};color:#fff;font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center">{{ '✓' if ok else '!' }}</span><div><div style="font-weight:600">{{ t(key) }}</div><div class="s">{{ detail }}</div></div></div>{% endfor %}</div></section>
<div class="row"><section class="card" style="flex:1 1 440px;min-width:0" aria-labelledby="sec"><h2 id="sec">{{ t('by_sector') }}</h2><p class="sub" style="font-size:13px">{{ t('sector_rule') }}</p>
{% for s in m.sectors %}<div style="display:grid;grid-template-columns:150px minmax(0,1fr) 110px;align-items:center;gap:12px;padding:7px 0;font-size:14px"><span>{{ s.name }}</span><div class="bar" style="height:10px"><div style="height:10px;width:{{ s.bar }}%;background:{{ '#B4460F' if s.n >= 5 else '#4C6A8A' }}"></div></div><span class="mono" style="text-align:right">{{ pct(s.pct, sign=False) }} · {{ s.n }}</span></div>{% endfor %}</section>
<section class="card" style="flex:1 1 440px;min-width:0" aria-labelledby="th"><h2 id="th">{{ t('by_theme') }}</h2><p class="sub" style="font-size:13px">{{ t('theme_rule') }}</p>
<div class="list">{% for x in m.themes %}<div style="display:flex;justify-content:space-between;gap:12px;font-size:14px"><div><div style="font-weight:600">{{ x.name }}</div><div class="mono" style="color:var(--muted);font-size:13px">{{ x.syms }}</div></div><div class="mono" style="font-weight:600">{{ pct(x.pct, sign=False) }}</div></div>{% else %}<p class="sub">—</p>{% endfor %}</div></section><section class="card" style="flex:1 1 440px;min-width:0" aria-labelledby="cr"><div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><h2 id="cr">{{ t('by_corr') }}</h2><span class="badge b-grey">{{ t('info_only') }}</span></div><p class="sub" style="font-size:13px">{{ t('corr_rule') }}</p>
{% for blk in cors %}{% set cor = blk.c %}<div style="border-top:1px solid var(--soft);padding-top:12px;margin-top:12px"><div style="font-weight:600;margin-bottom:6px">{{ t(blk.title) }}</div>
{% if not cor %}<p class="sub" style="font-size:13px">{{ t('corr_err') if blk.err else t(blk.empty_key) }}</p>{% else %}
<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px"><div><span class="mono" style="font-size:24px;font-weight:700">{{ '%.2f'|format(cor.avg) }}</span> <span class="sub" style="font-size:13px">{{ t('corr_avg') }}</span></div><span class="badge {{ 'b-ok' if cor.level == 'well' else 'b-warn' }}">{{ t('corr_' ~ cor.level) }}</span></div>
<div class="bar" style="height:10px;margin:8px 0 12px"><div style="height:10px;width:{{ cor.bar }}%;background:{{ '#0B6E66' if cor.level == 'well' else '#B4460F' }}"></div></div>
<div style="font-size:14px"><span class="mono" style="font-size:20px;font-weight:700">{{ cor.eff }}</span> {{ t('corr_eff', n=cor.n) }}</div>
{% if cor.groups %}<div class="s" style="font-weight:600;margin-top:12px">{{ t('corr_groups') }}</div>{% for g in cor.groups %}<div style="font-size:14px;padding:3px 0">{% for x in g %}{{ nm(x) or x }}{{ ', ' if not loop.last }}{% endfor %}</div>{% endfor %}{% else %}<p class="sub" style="font-size:13px;margin-top:10px">{{ t('corr_nogroup') }}</p>{% endif %}
<div class="s" style="font-weight:600;margin-top:12px">{{ t('corr_pairs') }}</div>{% for a, b, c in cor.top %}<div style="display:flex;justify-content:space-between;gap:12px;font-size:14px;padding:2px 0"><span>{{ nm(a) or a }} · {{ nm(b) or b }}</span><span class="mono">{{ '%.2f'|format(c) }}</span></div>{% endfor %}{% endif %}</div>{% endfor %}
<p class="sub" style="font-size:12px;margin:12px 0 0">{{ t('corr_note') }}</p></section>
</div>
<section class="card" style="padding:28px" aria-labelledby="sc"><h2 id="sc">{{ t('whatif') }}</h2><p class="sub" style="margin-bottom:12px">{{ t('whatif_note') }}</p>
{% if herr or (hold and hold.error) %}<p class="sub" style="font-size:13px;margin-bottom:8px">{{ t('hold_err') }}</p>{% elif not hold or hold.empty %}<p class="sub" style="font-size:13px;margin-bottom:8px">{{ t('hold_empty') }}</p>{% elif hold.scen %}<p class="sub" style="font-size:13px;margin-bottom:8px">{{ t('hold_meta', n=hold.n, inv=pct(hold.invested_pct, sign=False), cash=pct(hold.cash_pct, sign=False)) }}</p>{% endif %}
<div class="legend" style="margin-bottom:8px"><span><span style="width:14px;height:10px;background:#B4460F;border-radius:2px"></span>{{ t('your_basket') }}</span>{% if hold and hold.scen %}<span><span style="width:14px;height:10px;background:#4C6A8A;border-radius:2px"></span>{{ t('your_holdings') }}</span>{% endif %}<span><span style="width:14px;height:10px;background:#A9B3C1;border-radius:2px"></span>S&amp;P 500</span><span><span style="width:2px;height:14px;background:#0E1A2B"></span>{{ t('limit') }}</span></div>
{% for x in m.scen %}<div style="display:flex;flex-wrap:wrap;gap:8px 20px;padding:16px 0;border-top:1px solid var(--soft);align-items:center">
<div style="flex:1 1 240px;min-width:0"><div style="font-weight:600">{{ x.label[1] if lang == 'de' else x.label[0] }}</div>{% if x.names %}<div class="sub" style="font-size:12px">{{ t('hit_hardest') }}: <span class="mono">{{ x.names }}</span></div>{% endif %}</div>
<div style="flex:2 1 400px;min-width:0;display:flex;flex-direction:column;gap:6px">
<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="position:relative;height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#B4460F;border-radius:3px;width:{{ x.b_bar }}%"></div><div style="position:absolute;top:-4px;width:2px;height:22px;background:#0E1A2B;left:{{ x.l_bar }}%"></div></div><span class="mono" style="text-align:right;font-weight:600">{{ pct(x.basket) }}</span></div>
{% if x.hold is not none %}<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#4C6A8A;border-radius:3px;width:{{ x.h_bar }}%"></div></div><span class="mono" style="text-align:right;font-weight:600;color:#4C6A8A">{{ pct(x.hold) }}</span></div>{% endif %}
<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#A9B3C1;border-radius:3px;width:{{ x.s_bar }}%"></div></div><span class="mono" style="text-align:right;color:#33475B">{{ pct(x.spy) }}</span></div></div>
<span class="badge {{ 'b-ok' if x.status == 'within' else 'b-warn' }}" style="flex:0 0 110px;text-align:center">{{ t(x.status) }}</span></div>{% endfor %}
{% if sev %}<div style="display:flex;flex-wrap:wrap;gap:8px 20px;padding:16px 0;border-top:2px solid var(--soft);align-items:center">
<div style="flex:1 1 240px;min-width:0"><div style="font-weight:600">{{ t('severe_label') }}</div></div>
<div style="flex:2 1 400px;min-width:0;display:flex;flex-direction:column;gap:6px">
<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#B4460F;border-radius:3px;width:{{ sev.b_bar }}%"></div></div><span class="mono" style="text-align:right;font-weight:600">{{ pct(sev.basket) }}</span></div>
{% if sev.hold is not none %}<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#4C6A8A;border-radius:3px;width:{{ sev.h_bar }}%"></div></div><span class="mono" style="text-align:right;font-weight:600;color:#4C6A8A">{{ pct(sev.hold) }}</span></div>{% endif %}
<div style="display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:10px;align-items:center"><div style="height:14px;background:var(--bg);border-radius:3px"><div style="height:14px;background:#A9B3C1;border-radius:3px;width:{{ sev.s_bar }}%"></div></div><span class="mono" style="text-align:right;color:#33475B">{{ pct(sev.spy) }}</span></div></div>
<span class="badge b-grey" style="flex:0 0 110px;text-align:center">{{ t('info_only') }}</span></div>
<p class="sub" style="font-size:13px;margin:8px 0 0">{{ t('severe_note') }}</p>{% endif %}</section>

{% if m %}<section class="card" style="padding:28px" aria-labelledby="sh"><div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px"><h2 id="sh">{{ t('shadow_title') }}</h2><span class="badge b-grey">{{ t('info_only') }}</span></div><p class="sub" style="margin-bottom:12px">{{ t('shadow_intro') }}</p>
{% if shd_err %}<p class="sub" style="font-size:13px">{{ t('shadow_err') }}</p>{% elif not shd or not shc %}<p class="sub" style="font-size:13px">{{ t('shadow_wait') }}</p>{% else %}
<div class="legend" style="margin-bottom:8px"><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#B4460F" stroke-width="3"/></svg>{{ t('shadow_cur') }} · {{ money(shc.end[0], dec=0) }}</span><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#0B6E66" stroke-width="3"/></svg>{{ t('shadow_low') }} · {{ money(shc.end[1], dec=0) }}</span><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#7D8899" stroke-width="2.5"/></svg>S&amp;P 500 · {{ money(shc.end[2], dec=0) }}</span></div>
<svg viewBox="-8 -12 {{ shc.w + 16 }} {{ shc.h + 30 }}" style="width:100%;height:auto;display:block" role="img" aria-label="{{ t('shadow_title') }}">
{% for y, v in shc.grid %}<line x1="0" y1="{{ y }}" x2="{{ shc.w }}" y2="{{ y }}" stroke="#E8ECF1"/><text x="{{ shc.w }}" y="{{ y - 4 }}" text-anchor="end" font-size="11" fill="#4A5568">{{ money(v, dec=0) }}</text>{% endfor %}
<polyline fill="none" stroke="#7D8899" stroke-width="2.5" points="{{ shc.c }}"/>
<polyline fill="none" stroke="#B4460F" stroke-width="2.5" points="{{ shc.a }}"/>
<polyline fill="none" stroke="#0B6E66" stroke-width="3" points="{{ shc.b }}"/>
<text x="0" y="{{ shc.h + 16 }}" font-size="11" fill="#4A5568">{{ date(shc.first) }}</text><text x="{{ shc.w }}" y="{{ shc.h + 16 }}" font-size="11" fill="#4A5568" text-anchor="end">{{ date(shc.last) }}</text></svg>
<p class="sub" style="font-size:13px;margin:10px 0 4px">{{ t('shadow_exposure', a=shd.ai_cur, b=shd.ai_low) }}</p>
{% if shd.swaps %}<div class="list" style="margin-top:8px">{% for o, n in shd.swaps %}<div style="font-size:14px">{{ nm(o) or o }} <span class="mono" style="color:var(--muted)">{{ o }}</span> → {% if n %}{{ nm(n) or n }} <span class="mono" style="color:var(--muted)">{{ n }}</span>{% else %}<span style="color:var(--muted)">{{ t('shadow_dropped') }}</span>{% endif %}</div>{% endfor %}</div>{% else %}<p class="sub" style="font-size:13px">{{ t('shadow_noswap') }}</p>{% endif %}
<p class="sub" style="font-size:12px;margin:12px 0 0">{{ t('shadow_note') }}</p>{% endif %}</section>{% endif %}

{% if m.risks %}<section class="card" style="padding:28px" aria-labelledby="nw"><h2 id="nw">{{ t('news_watch') }}</h2><p class="sub" style="margin-bottom:16px">{{ t('news_watch_note') }}</p>
<div class="grid" style="gap:12px">{% for r in m.risks %}<div class="tile" style="display:flex;flex-direction:column;gap:10px"><div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><strong style="font-size:16px">{{ rname(r.name) }}</strong><span class="badge {{ 'b-ok' if r.level == 'low' else 'b-warn' }}">{{ rlevel(r.level) }}</span></div>{% if r.bottom %}<div style="font-size:14px;font-weight:600;line-height:1.45">{{ plain(r.bottom) }}</div>{% endif %}{% if r.prices %}<div style="font-size:13px;color:#33475B;line-height:1.5"><div class="s" style="font-weight:600">{{ t('rk_prices') }}</div>{{ plain(r.prices) }}</div>{% endif %}{% if r.news %}<div style="font-size:13px;color:#33475B;line-height:1.5"><div class="s" style="font-weight:600">{{ t('rk_news') }}</div>{{ plain(r.news) }}</div>{% endif %}{% if not (r.prices or r.news or r.bottom) and r.text %}<div style="font-size:13px;color:#33475B;line-height:1.5">{{ plain(r.text) }}</div>{% endif %}{% if r.trigger %}<div class="s"><strong>{{ t('act_if') }}:</strong> {{ plain(r.trigger, True) }}</div>{% endif %}</div>{% endfor %}</div></section>{% endif %}
{% endif %}{% endblock %}"""

ACTIVITY = """{% extends 'base.html' %}{% block body %}
<div><h1>{{ t('activity') }}</h1><p class="sub">{{ t('activity_intro') }}</p></div>
{% if serr %}<div class="warnbox">{{ t(serr) }}</div>{% endif %}
<nav class="chips" aria-label="Filter">{% for k in ['all','buys','sells','waits','checks'] %}<a href="/app/activity?f={{ k }}" class="{{ 'on' if f == k else '' }}" aria-current="{{ 'true' if f == k else 'false' }}">{{ t(k) }}</a>{% endfor %}</nav>
<section class="card" style="padding:8px 28px 20px">{% for d in days %}<div style="padding-top:20px"><h2 style="font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">{{ d.at }}{% if d.test %} · {{ t('test_run') }}{% endif %}</h2>
{% for i in d.entries %}<div class="item" style="flex-wrap:wrap;padding:14px 0;border-top:1px solid var(--soft)"><span class="tag t-{{ i.tag }}" style="height:fit-content">{{ tag(i.tag) }}</span><div style="flex:1 1 420px;min-width:0"><div style="font-weight:600">{{ i.title }}</div><div class="why mono" style="font-size:12px">{{ t('rule') }}: {{ i.why }}</div></div><div class="mono" style="font-weight:600;min-width:90px;text-align:right">{{ money(i.amount|float) if i.amount else '' }}</div></div>{% endfor %}</div>
{% else %}<p class="sub" style="padding-top:16px">{{ t('no_activity') }}</p>{% endfor %}</section>
{% endblock %}"""

REPORTS = """{% extends 'base.html' %}{% block body %}
<div><h1>{{ t('reports') }}</h1></div>
<div class="row"><section class="card" style="flex:1 1 420px" aria-labelledby="wr"><h2 id="wr">{{ t('weekly_report') }}</h2><p class="sub">{{ t('weekly_soon') }}</p></section>
<section class="card" style="flex:1 1 420px" aria-labelledby="hw"><h2 id="hw">{{ t('how') }}</h2><p class="sub">{{ 'Ziel, Strategie, Regeln, Backtest-Ergebnisse und Risiken – vollständig erklärt.' if lang == 'de' else 'Goal, strategy, rules, backtest results and risks — fully explained.' }}</p><p style="margin:12px 0 0"><a class="btn" href="/app/how">{{ t('how') }} →</a></p></section></div>
<section class="card" style="padding:32px" aria-labelledby="dl"><h2 id="dl" style="font-size:22px">{{ t('downloads') }}</h2><p class="sub">{{ t('downloads_note') }}</p>
{% for f, k in [('latest-run.json','dl_run'),('trades.csv','dl_trades'),('audit-log.csv','dl_audit'),('backtests.md','dl_bt')] %}
<div class="dl"><div class="d"><strong>{{ t(k) }}</strong><div class="sub" style="margin-top:3px;font-size:14px">{{ t(k ~ '_t') }}</div></div><a class="btn" href="/app/download/{{ f }}">{{ t('download') }}</a></div>{% endfor %}</section>
{% if status %}<section class="card" aria-labelledby="sy"><h2 id="sy">{{ t('system') }}</h2><dl style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:14px 0 0;font-size:14px">
<div><dt class="sub" style="margin:0">{{ t('last_daily') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ status.daily.at if status.daily else '—' }} {% if status.daily %}<span class="badge b-grey">{{ status.daily.mode }}</span>{% endif %}</dd></div>
<div><dt class="sub" style="margin:0">{{ t('last_weekly') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ status.weekly or '—' }}</dd></div>
<div><dt class="sub" style="margin:0">{{ t('research_desk') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ status.desk or '—' }}</dd></div>
<div><dt class="sub" style="margin:0">{{ t('sheet') }}</dt><dd style="margin:2px 0 0;font-weight:600">{{ t('connected') if status.sheet else t('not_connected') }}</dd></div>
<div style="grid-column:1/-1"><dt class="sub" style="margin:0">{{ t('errors') }}</dt><dd class="mono" style="margin:2px 0 0;font-size:12px">{{ (status.daily.errors if status.daily else '') or t('none') }}</dd></div></dl></section>{% endif %}
{% endblock %}"""

PROFILE = """{% extends 'base.html' %}{% block body %}
<div style="max-width:640px;width:100%;margin:0 auto;display:flex;flex-direction:column;gap:20px">
<div><h1>{{ t('profile') }}</h1><p class="sub">{{ t('profile_intro') }}</p></div>
{% if saved %}<div class="note" role="status">{{ t('saved') }}</div>{% endif %}
<form class="card stack" method="post" action="/app/profile"><input type="hidden" name="csrf" value="{{ csrf }}">
<div class="stack" style="gap:6px"><label for="n">{{ t('greet_as') }}</label><input id="n" name="name" type="text" maxlength="30" value="{{ me.name }}"><span class="sub" style="margin:0;font-size:13px">{{ t('greet_eg') }}</span></div>
<fieldset style="border:0;margin:0;padding:0"><legend style="font-weight:600;margin-bottom:10px">{{ t('language') }}</legend><div class="opt">
<label><input type="radio" name="lang" value="de" {{ 'checked' if me.lang == 'de' else '' }}> Deutsch</label><label><input type="radio" name="lang" value="en" {{ 'checked' if me.lang == 'en' else '' }}> English</label></div></fieldset>
<fieldset style="border:0;margin:0;padding:0"><legend style="font-weight:600;margin-bottom:10px">{{ t('text_size') }}</legend><div class="opt">
<label><input type="radio" name="size" value="normal" {{ '' if me.large else 'checked' }}> {{ t('normal') }}</label><label><input type="radio" name="size" value="large" {{ 'checked' if me.large else '' }}> {{ t('large') }}</label></div></fieldset>
<button class="primary" type="submit">{{ t('save') }}</button><p class="sub" style="margin:0;font-size:13px">{{ t('pw_note') }}</p></form>
{% if not me.owner %}<p class="sub">{{ t('view_note') }}</p>{% endif %}</div>
{% endblock %}"""

HOW_EN = """
<section class="card prose"><h2>1. Goal and honest expectations</h2><p>The goal is to beat the S&amp;P 500 (the 500 largest US companies) after tax, with deposits like a savings plan: $1,000 to start, then $100 a month. Horizon 6 to 24 months.</p><p>Realistically, about 90% of professional funds do <em>not</em> beat the S&amp;P 500 over 15 years. A well-built system might add 1–3 points a year — or lose some. In any single year a 20-stock basket differs from the index by ±5–10 points by pure chance. Skill versus luck only shows after years, so every decision is logged and compared with the index.</p></section>
<section class="card prose"><h2>2. The strategy in one sentence</h2><p style="font-size:18px;font-weight:600;color:var(--ink)">Buy the 20 stocks with the strongest price trend of the last 12 months, hold them at least 6 months, and sell earlier only when the trend or the story behind it clearly breaks.</p><p>This "momentum" effect is one of the best-documented in finance research: stocks that rose strongly for a year tend to keep going for a while. The 6-month hold comes from tax law: in Luxembourg, private investors' share gains are generally tax-free after 6 months (to be confirmed with a tax adviser before real money).</p></section>
<section class="card prose"><h2>3. Who decides what: code and AI</h2><p><strong>Numbers are decided by code, text is read by AI.</strong> The code follows fixed, checkable rules. The AI can never add a stock, set an amount or trigger a sale on its own.</p><ul>
<li><strong>Sunday 20:00 (code):</strong> rank all S&amp;P 500 stocks by 12-month trend, apply safety filters, pick 20.</li>
<li><strong>Sunday (AI, majority):</strong> three AI models (Claude, GPT, Kimi) check each stock for warning signs; a warning counts only if most agree.</li>
<li><strong>Sunday (AI research with sources):</strong> per stock: why we own it, what would make us sell, when results are due.</li>
<li><strong>Weekdays 20:00 (AI, 2 of 3 + price):</strong> two AI analysts read the news; three other models vote whether a story is really broken.</li>
<li><strong>Weekdays 20:00 (code):</strong> calculate and place buys and sells.</li>
<li><strong>Every 30 minutes (code):</strong> crash alarm — if the market falls 3% or a held stock 7% in a day, the daily check starts at once.</li></ul></section>
<section class="card prose"><h2>4. The protection rules</h2><ul>
<li><strong>Spread:</strong> 20 stocks, at most 5 per sector and 2 per theme.</li>
<li><strong>Careful buying:</strong> each new stock in three parts over three weeks; no buying after a +15% jump in 5 days, a −15% fall in 10 days, or in the 4 days before results.</li>
<li><strong>Trend broken:</strong> sell when a stock is more than 25% below its high since purchase <em>and</em> below its 150-day average.</li>
<li><strong>Emergency brake:</strong> sell at −35% from the purchase price.</li>
<li><strong>Story broken:</strong> sell only if 2 of 3 AI reviewers agree <em>and</em> the price confirms it (−8% since the news), or all 3 agree.</li>
<li><strong>Crash limit:</strong> in every scenario the basket may lose at most 1.5× the S&amp;P 500; otherwise the riskiest stock is replaced.</li>
<li><strong>No borrowing:</strong> never buys with borrowed money; 5% always stays in cash.</li></ul></section>
<section class="card prose"><h2>5. What the tests on past data show</h2><p>Tested with the actual S&amp;P 500 members of each month, January 2021 to March 2026.</p><ul>
<li><strong>Top 20 by 12-month trend, held 6 months:</strong> +4.6 points per half-year ahead of the S&amp;P; better in 67% of half-years; positive in all three market phases.</li>
<li><strong>Same, strongest with 3× weight:</strong> +5.8 points per half-year — that is why money is weighted by rank.</li>
<li><strong>Our full rules, after 40% tax on sales within 6 months:</strong> +4.2 to +7.4 points a year depending on variant; the built-in one (+7.4) was better in 79% of start months; worst drawdown −22% on average.</li>
<li><strong>Valuation ("cheap stocks"):</strong> −3.3 points — did not work, so it is information only.</li></ul>
<p><strong>Why these numbers may be too good:</strong> the period was dominated by the AI boom; there are only about 10 independent half-years; trading costs are not included; no "momentum crash" like spring 2009 happened in the period. A first test version with biased data showed +12.7 points — after the fix it was +4.6. We therefore expect the lower end.</p></section>
<section class="card prose"><h2>6. What can go wrong</h2><ul>
<li><strong>If the AI bubble bursts,</strong> the basket would lose an estimated 17%, the S&amp;P about 12%. Real crashes are usually worse than any estimate.</li>
<li><strong>Swings:</strong> the basket moves about 1.4× as much as the market. Minus 20% in a bad half-year is possible.</li>
<li><strong>Technology:</strong> if a service is down, nothing happens that day — the system then simply does not trade.</li>
<li><strong>AI mistakes:</strong> a model can misread a headline; every sale needs several models <em>and</em> a confirming price.</li></ul>
<p><strong>Running costs:</strong> about $0.22 a week for the Sunday review plus a few cents a day for the news check. Server and data sources are free.</p></section>
<section class="card prose"><h2>7. Check it yourself</h2><p>Every code change and every decision is recorded. The latest run, all orders, the audit log and the backtest reports can be downloaded on the <a href="/app/reports">Reports</a> page.</p></section>"""

HOW_DE = """
<section class="card prose"><h2>1. Ziel und ehrliche Erwartung</h2><p>Ziel ist, nach Steuern besser abzuschneiden als der S&amp;P 500 (die 500 größten US-Firmen) – mit Einzahlungen wie bei einem Sparplan: Start mit 1.000 $, dann 100 $ pro Monat. Anlagehorizont 6 bis 24 Monate.</p><p>Realistisch: Rund 90 % der professionellen Fonds schlagen den S&amp;P 500 über 15 Jahre <em>nicht</em>. Ein gut gebautes System kann vielleicht 1–3 Prozentpunkte pro Jahr mehr erreichen – oder auch weniger. In einem einzelnen Jahr weicht ein Korb aus 20 Aktien rein zufällig um ±5–10 Punkte vom Index ab. Ob Können oder Glück, zeigt sich erst nach Jahren. Darum wird jede Entscheidung protokolliert und mit dem Index verglichen.</p></section>
<section class="card prose"><h2>2. Die Strategie in einem Satz</h2><p style="font-size:18px;font-weight:600;color:var(--ink)">Kaufe die 20 Aktien mit dem stärksten Kurstrend der letzten 12 Monate, halte sie mindestens 6 Monate, und verkaufe früher nur, wenn der Trend oder die Geschichte dahinter klar bricht.</p><p>Dieser „Momentum“-Effekt ist einer der am besten belegten in der Finanzforschung: Aktien, die ein Jahr lang stark gestiegen sind, laufen im Schnitt noch eine Weile weiter. Die 6 Monate Haltedauer kommen aus dem Steuerrecht: In Luxemburg sind Kursgewinne von Privatanlegern nach 6 Monaten in der Regel steuerfrei (vor echtem Geld mit einem Steuerberater prüfen).</p></section>
<section class="card prose"><h2>3. Wer entscheidet was: Programmcode und KI</h2><p><strong>Zahlen entscheidet der Code, Texte liest die KI.</strong> Der Code folgt festen, nachprüfbaren Regeln. Die KI darf nie eine Aktie hinzufügen, keinen Betrag festlegen und keinen Verkauf allein auslösen.</p><ul>
<li><strong>Sonntag 20:00 (Code):</strong> Rangliste aller S&amp;P-500-Aktien nach 12-Monats-Trend, Sicherheitsfilter, Auswahl der 20.</li>
<li><strong>Sonntag (KI, Mehrheit):</strong> Drei KI-Modelle (Claude, GPT, Kimi) prüfen jede Aktie auf Warnsignale; eine Warnung zählt nur, wenn die Mehrheit zustimmt.</li>
<li><strong>Sonntag (KI-Recherche mit Quellen):</strong> je Aktie: Warum besitzen wir sie, was würde uns zum Verkauf bringen, wann kommen Quartalszahlen.</li>
<li><strong>Werktags 20:00 (KI, 2 von 3 + Kurs):</strong> Zwei KI-Analysten lesen die Nachrichten; drei andere Modelle stimmen ab, ob eine Geschichte wirklich gebrochen ist.</li>
<li><strong>Werktags 20:00 (Code):</strong> Käufe und Verkäufe berechnen und ausführen.</li>
<li><strong>Alle 30 Minuten (Code):</strong> Crash-Alarm – fällt der Markt 3 % oder eine gehaltene Aktie 7 % an einem Tag, startet die Tagesprüfung sofort.</li></ul></section>
<section class="card prose"><h2>4. Die Schutzregeln</h2><ul>
<li><strong>Streuung:</strong> 20 Aktien, höchstens 5 pro Branche und 2 pro Thema.</li>
<li><strong>Vorsichtig kaufen:</strong> jede neue Aktie in drei Teilen über drei Wochen; kein Kauf nach +15 % in 5 Tagen, nach −15 % in 10 Tagen oder in den 4 Tagen vor Quartalszahlen.</li>
<li><strong>Trend gebrochen:</strong> Verkauf, wenn eine Aktie mehr als 25 % unter ihrem Höchststand seit dem Kauf <em>und</em> unter ihrem 150-Tage-Durchschnitt liegt.</li>
<li><strong>Notbremse:</strong> Verkauf bei −35 % gegenüber dem Kaufpreis.</li>
<li><strong>Geschichte gebrochen:</strong> Verkauf nur, wenn 2 von 3 KI-Prüfern zustimmen <em>und</em> der Kurs es bestätigt (−8 % seit der Nachricht), oder alle 3 zustimmen.</li>
<li><strong>Crash-Grenze:</strong> In jedem Szenario darf der Korb höchstens das 1,5-Fache des S&amp;P 500 verlieren; sonst wird die riskanteste Aktie ersetzt.</li>
<li><strong>Kein Kredit:</strong> Es wird nie mit geliehenem Geld gekauft; 5 % bleiben immer als Bargeld.</li></ul></section>
<section class="card prose"><h2>5. Was die Tests mit historischen Daten zeigen</h2><p>Getestet mit den echten S&amp;P-500-Mitgliedern des jeweiligen Monats, Januar 2021 bis März 2026.</p><ul>
<li><strong>Top 20 nach 12-Monats-Trend, 6 Monate halten:</strong> +4,6 Punkte je Halbjahr vor dem S&amp;P; in 67 % der Halbjahre besser; in allen drei Marktphasen positiv.</li>
<li><strong>Dasselbe, Stärkste mit 3× Gewicht:</strong> +5,8 Punkte je Halbjahr – deshalb wird nach Rang gewichtet.</li>
<li><strong>Unsere Regeln komplett, nach 40 % Steuer auf Verkäufe unter 6 Monaten:</strong> +4,2 bis +7,4 Punkte pro Jahr je nach Variante; die eingebaute Variante (+7,4) war in 79 % der Startmonate besser; schlimmster Rückgang im Schnitt −22 %.</li>
<li><strong>Bewertung („günstige Aktien“):</strong> −3,3 Punkte – hat nicht funktioniert, deshalb nur Information.</li></ul>
<p><strong>Warum diese Zahlen zu gut sein könnten:</strong> Der Zeitraum war stark von der KI-Börse geprägt; es gibt nur etwa 10 unabhängige Halbjahre; Handelskosten sind nicht eingerechnet; ein „Momentum-Crash“ wie im Frühjahr 2009 kam nicht vor. Eine erste Testversion mit verzerrten Daten hatte +12,7 Punkte gezeigt – nach der Korrektur waren es +4,6. Wir rechnen deshalb eher mit dem unteren Ende.</p></section>
<section class="card prose"><h2>6. Was schiefgehen kann</h2><ul>
<li><strong>Platzt die KI-Blase,</strong> verliert der Korb geschätzt etwa 17 %, der S&amp;P etwa 12 %. Echte Crashs sind meist schlimmer als jede Schätzung.</li>
<li><strong>Schwankungen:</strong> Der Korb schwankt etwa 1,4-mal so stark wie der Markt. Minus 20 % in einem schlechten Halbjahr sind möglich.</li>
<li><strong>Technik:</strong> Fällt ein Dienst aus, läuft an diesem Tag nichts – das System handelt dann einfach nicht.</li>
<li><strong>KI-Fehler:</strong> Ein Modell kann eine Nachricht falsch lesen; jeder Verkauf braucht mehrere Modelle <em>und</em> einen bestätigenden Kurs.</li></ul>
<p><strong>Laufende Kosten:</strong> ca. 0,22 $ pro Woche für die Sonntags-Prüfung plus wenige Cent pro Tag für die Nachrichtenprüfung. Server und Datenquellen sind kostenlos.</p></section>
<section class="card prose"><h2>7. Selbst prüfen</h2><p>Jede Programmänderung und jede Entscheidung wird festgehalten. Der letzte Lauf, alle Orders, das Prüfprotokoll und die Backtest-Berichte lassen sich auf der Seite <a href="/app/reports">Berichte</a> herunterladen.</p></section>"""

HOW = """{% extends 'base.html' %}{% block body %}<div style="max-width:900px;width:100%;margin:0 auto;display:flex;flex-direction:column;gap:24px">
<div><a href="/app/reports">← {{ t('reports') }}</a><h1 style="font-size:32px;margin-top:10px">{{ 'So funktioniert es: der Ansatz, die Regeln, die Belege' if lang == 'de' else 'How it works: the approach, the rules, the evidence' }}</h1></div>
<div class="warnbox">{{ 'Wichtig: Derzeit ist das ein Test mit Spielgeld. Es wird kein echtes Geld angelegt, und niemand legt Geld für andere an. Nichts hier ist eine Anlageberatung. Vergangene Ergebnisse versprechen keine zukünftigen.' if lang == 'de' else 'Important: this is currently a test with play money. No real money is invested and nobody invests for anyone else. Nothing here is investment advice. Past results do not promise future results.' }}</div>
{% if lang == 'de' %}""" + HOW_DE + """{% else %}""" + HOW_EN + """{% endif %}</div>{% endblock %}"""

STOCK = """{% extends 'base.html' %}{% block body %}
<div><a href="/app/basket" style="font-size:14px">{{ t('back_basket') }}</a></div>
{% if not st %}<div class="card"><h1 style="font-size:24px"><span class="mono">{{ sym }}</span></h1><p class="sub" style="margin:0">{{ t('no_research') }}</p></div>
{% else %}<section class="card" style="padding:28px;display:flex;flex-direction:column;gap:22px" aria-labelledby="sk">
<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;align-items:flex-start"><div><h1 id="sk" style="font-size:28px;margin:0">{{ nm(st.symbol) or st.symbol }}{% if nm(st.symbol) %} <span class="mono" style="font-size:16px;color:var(--muted)">{{ st.symbol }}</span>{% endif %}{% if st.cluster %} · <span style="font-weight:500">{{ st.cluster }}</span>{% endif %}</h1>
<p class="sub" style="margin:6px 0 0">{{ st.sector }}</p></div>
<span class="badge {{ 'b-ok' if st.in_basket else 'b-grey' }}" style="font-size:13px;padding:6px 12px">{% if st.in_basket %}{{ t('st_in', r=st.rank or '—') }}{% elif st.rank %}{{ t('st_out', r=st.rank) }}{% else %}{{ t('st_none') }}{% endif %}</span></div>
{% if st.own %}<div class="tile" style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px"><div><strong>{{ t('own_it') }}</strong> <span style="color:var(--muted)">{{ t('own_since', d=date(st.own.since) if st.own.since else '—', v=money(st.own.value), g=pct(st.own.gain)) }}</span></div><a href="/app/holdings?s={{ st.symbol }}">{{ t('see_holding') }}</a></div>{% endif %}
<div><h2 style="font-size:16px;margin:0 0 6px">{{ t('px_title') }}</h2>
{% if pxc %}<div style="display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;margin-bottom:8px"><span class="mono" style="font-size:30px;font-weight:700">{{ money(px.last) }}</span><span style="font-weight:600;color:{{ '#0B6E66' if px.day >= 0 else '#B4460F' }}">{{ pct(px.day) }} {{ t('px_today') }}</span><span class="sub" style="font-size:13px;margin:0">{{ t('px_asof', d=date(px.last_date)) }}</span></div>
<div class="legend" style="margin-bottom:6px"><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#0B6E66" stroke-width="3"/></svg>{{ nm(st.symbol) or st.symbol }} · {{ pct(px.ret) }}</span><span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="#7D8899" stroke-width="2.5"/></svg>S&amp;P 500 · {{ pct(px.spy_ret) }}</span>{% if pxc.mark is not none %}<span><svg width="22" height="10" aria-hidden="true"><line x1="11" y1="0" x2="11" y2="10" stroke="#B4460F" stroke-width="2" stroke-dasharray="3 2"/></svg>{{ t('px_bought') }}</span>{% endif %}</div>
<svg id="pxsvg" data-px="{{ pxc.json }}" viewBox="-62 -12 {{ pxc.w + 150 }} {{ pxc.h + 34 }}" style="width:100%;height:auto;display:block;touch-action:pan-y;cursor:crosshair" role="img" aria-label="{{ t('px_title') }}">
{% for y, v in pxc.grid %}<line x1="0" y1="{{ y }}" x2="{{ pxc.w }}" y2="{{ y }}" stroke="#E8ECF1"/><text x="-8" y="{{ y + 4 }}" text-anchor="end" font-size="11" fill="#4A5568">{{ money(v, dec=pxc.dec) }}</text>{% endfor %}
{% for mo in pxc.months %}<line x1="{{ mo.x }}" y1="{{ pxc.h }}" x2="{{ mo.x }}" y2="{{ pxc.h + 4 }}" stroke="#A9B3C1"/><text x="{{ mo.x }}" y="{{ pxc.h + 17 }}" text-anchor="middle" font-size="11" fill="#4A5568">{{ t('mon_' ~ mo.m) }}{% if mo.m == 1 or loop.first %} {{ mo.y[2:] }}{% endif %}</text>{% endfor %}
<line x1="0" y1="{{ pxc.start_y }}" x2="{{ pxc.w }}" y2="{{ pxc.start_y }}" stroke="#A9B3C1" stroke-dasharray="4 4"/>
{% if pxc.mark is not none %}<line x1="{{ pxc.mark }}" y1="0" x2="{{ pxc.mark }}" y2="{{ pxc.h }}" stroke="#B4460F" stroke-width="2" stroke-dasharray="3 3"/>{% endif %}
<polyline fill="none" stroke="#7D8899" stroke-width="2" points="{{ pxc.b }}"/>
<polyline fill="none" stroke="#0B6E66" stroke-width="3" points="{{ pxc.a }}"/>
<circle cx="{{ pxc.w }}" cy="{{ pxc.end_b }}" r="4" fill="#7D8899"/><text x="{{ pxc.w + 10 }}" y="{{ pxc.end_b + 4 }}" font-size="12" fill="#4A5568">S&amp;P</text>
<circle cx="{{ pxc.w }}" cy="{{ pxc.end }}" r="5.5" fill="#0B6E66"/><text x="{{ pxc.w + 10 }}" y="{{ pxc.end + 4 }}" font-size="13" font-weight="700" fill="#0B6E66">{{ money(px.last, dec=0 if px.last >= 100 else 2) }}</text>
<g id="pxh" style="display:none;pointer-events:none"><line y1="0" y2="{{ pxc.h }}" stroke="#4A5568" stroke-width="1"/><circle class="ca" r="5" fill="#0B6E66" stroke="#fff" stroke-width="2"/><circle class="cb" r="4" fill="#7D8899" stroke="#fff" stroke-width="2"/><rect width="200" height="64" rx="8" fill="#fff" stroke="#CBD3DD"/><text font-size="12" font-weight="700" fill="#0E1A2B"></text><text font-size="12" fill="#0B6E66"></text><text font-size="12" fill="#4A5568"></text></g></svg>
<script nonce="{{ nonce() }}">(function(){var s=document.getElementById('pxsvg');if(!s)return;var D=JSON.parse(s.dataset.px),g=document.getElementById('pxh'),ln=g.querySelector('line'),ca=g.querySelector('.ca'),cb=g.querySelector('.cb'),bx=g.querySelector('rect'),tx=g.querySelectorAll('text'),n=D.d.length-1;
function fm(v){return new Intl.NumberFormat(D.lang,{style:'currency',currency:'USD'}).format(v)}
function fd(i){return new Date(D.d[i]+'T12:00:00').toLocaleDateString(D.lang,{day:'numeric',month:'short',year:'numeric'})}
function Y(v){return D.h-(v-D.lo)/(D.hi-D.lo)*D.h}
function mv(e){var r=s.getBoundingClientRect(),vb=s.viewBox.baseVal,x=(e.clientX-r.left)/r.width*vb.width+vb.x,i=Math.max(0,Math.min(n,Math.round(x/D.w*n))),X=i*D.w/n,a=D.a[i],c=(a/D.a[0]-1)*100;
g.style.display='';ln.setAttribute('x1',X);ln.setAttribute('x2',X);ca.setAttribute('cx',X);ca.setAttribute('cy',Y(a));cb.setAttribute('cx',X);cb.setAttribute('cy',Y(D.b[i]));
var bxx=X>D.w/2?X-212:X+12,by=Math.max(0,Math.min(D.h-64,Math.min(Y(a),Y(D.b[i]))-32));bx.setAttribute('x',bxx);bx.setAttribute('y',by);
var T=[fd(i),D.t[0]+' '+fm(a)+' ('+(c>=0?'+':'')+c.toFixed(1)+'%)',D.t[1]+' '+fm(D.b[i])];
for(var k=0;k<3;k++){tx[k].setAttribute('x',bxx+10);tx[k].setAttribute('y',by+20+k*18);tx[k].textContent=T[k]}}
s.addEventListener('pointermove',mv);s.addEventListener('pointerdown',mv);s.addEventListener('pointerleave',function(){g.style.display='none'})})();</script>
<p class="sub" style="font-size:13px;margin:6px 0 0">{{ t('px_facts', hi=pct(px.from_high, dec=0), lo=pct(px.from_low, dec=0)) }}</p>
{% else %}<p class="sub" style="font-size:13px;margin:0">{{ t('px_none') }}</p>{% endif %}</div>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:28px">
<div class="prose" style="font-size:15px">
<h2 style="font-size:16px">{{ t('why_here') if st.in_basket else t('why_not') }}</h2>
{% if st.blocker %}<p><span class="badge b-warn">{{ t(st.blocker) }}</span></p>{% endif %}
<p>{{ st.thesis or '—' }}</p>
{% if st.reasoning and st.reasoning != st.thesis %}<p style="color:#33475B">{{ st.reasoning }}</p>{% endif %}
{% if st.decision %}<h2 style="font-size:16px;margin-top:14px">{{ t('week_decision') }}</h2><p>{{ st.decision }}</p>{% endif %}
{% if st.note %}<p><span class="badge b-warn">{{ st.note }}</span></p>{% endif %}
<h2 style="font-size:16px;margin-top:14px">{{ t('sell_if') }}</h2>{% if st.kill %}<ul>{% for k in st.kill %}<li>{{ k }}</li>{% endfor %}</ul>{% else %}<p>—</p>{% endif %}
</div>
<div style="display:flex;flex-direction:column;gap:10px;font-size:14px"><h2 style="font-size:16px">{{ t('key_facts') }}</h2>
{% for label, val in st.facts %}<div class="tile" style="display:flex;justify-content:space-between;gap:12px;padding:12px 14px"><span>{{ t(label) }}</span><strong style="text-align:right">{{ val }}</strong></div>{% endfor %}
{% if st.catalysts %}<h2 style="font-size:16px;margin-top:6px">{{ t('coming_up') }}</h2><ul class="list" style="margin:0">{% for c in st.catalysts %}<li style="padding:8px 0;display:flex;gap:12px"><span class="mono" style="color:var(--muted);min-width:90px">{{ date(c.date) }}</span><span>{{ c.event }}</span></li>{% endfor %}</ul>{% endif %}
</div></div>
{% if st.sources %}<div><h2 style="font-size:16px">{{ t('sources') }}</h2><ul style="margin:6px 0 0;padding-left:20px;font-size:13px;line-height:1.7">{% for u in st.sources %}<li><a href="{{ u.url }}" rel="noopener noreferrer" target="_blank">{{ u.host }}</a></li>{% endfor %}</ul></div>{% endif %}
{% if st.researched %}<p class="sub" style="margin:0;font-size:13px">{{ t('researched_on') }} {{ date(st.researched) }}</p>{% endif %}
</section>{% endif %}
{% endblock %}"""

TEMPLATES = {"base.html": BASE, "login.html": LOGIN, "overview.html": OVERVIEW, "holdings.html": HOLDINGS,
             "basket.html": BASKET, "risk.html": RISK, "activity.html": ACTIVITY, "reports.html": REPORTS,
             "profile.html": PROFILE, "how.html": HOW, "stock.html": STOCK}
