from __future__ import annotations

import html
import json
from decimal import Decimal

from .contracts import DailyAggregate, Report, report_to_dict


WIDTH = 960
HEIGHT = 380
LEFT = 72
RIGHT = 72
TOP = 32
BOTTOM = 58


def render_html(report: Report) -> str:
    chronological = list(reversed(report.days))
    chart_rows = [
        {
            "date": row.day.isoformat(),
            "capital": _number(row.average_capital_usd),
            "apr": _number(row.realized_apr_percent),
            "status": row.status,
            "claims": _number(row.gross_claim_usd),
            "net": _number(row.net_compound_usd),
            "fee": _number(row.automation_fee_usd),
            "gas": _number(row.gas_account_debit_usd),
            "count": row.claim_transaction_count,
        }
        for row in chronological
    ]
    chart_json = json.dumps(chart_rows, ensure_ascii=False, separators=(",", ":"))
    report_json = json.dumps(
        report_to_dict(report), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).replace("<", "\\u003c")
    capital_path = _series_path(chronological, "average_capital_usd")
    apr_path = _series_path(chronological, "realized_apr_percent")
    points = _point_markup(chronological)
    table = _table(report.days)
    current_x = _x(len(chronological) - 1, len(chronological))
    current_dash = (
        f'<path d="M{current_x:.2f} {TOP} V{HEIGHT - BOTTOM}" class="current-marker" stroke-dasharray="7 5" />'
        if chronological and chronological[-1].status == "partial"
        else ""
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VFAT Position Report</title>
<style>
:root{{--bg:#0d1321;--panel:#151e30;--grid:#33415c;--text:#edf2f4;--muted:#9fb0c8;--capital:#5dd39e;--apr:#ffca3a;--danger:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:24px}}h1{{margin:0 0 6px}}.sub{{color:var(--muted);margin-bottom:20px}}
.panel{{background:var(--panel);border-radius:14px;padding:18px;margin-bottom:18px;overflow:auto}}
.controls{{display:flex;gap:18px;margin-bottom:10px}}label{{cursor:pointer}}svg{{min-width:760px;width:100%;height:auto}}
.grid{{stroke:var(--grid);stroke-width:1}}.axis{{fill:var(--muted);font-size:12px}}.capital{{fill:none;stroke:var(--capital);stroke-width:3}}
.apr{{fill:none;stroke:var(--apr);stroke-width:3}}.point{{cursor:crosshair}}.current-marker{{stroke:var(--muted);opacity:.6}}
#tooltip{{position:fixed;display:none;pointer-events:none;background:#05080f;border:1px solid var(--grid);padding:9px;border-radius:8px;white-space:pre-line}}
table{{border-collapse:collapse;width:100%;min-width:1080px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(9),td:nth-child(9),th:last-child,td:last-child{{text-align:left}}tr.partial td:last-child{{color:var(--apr)}}tr.unreliable td:last-child{{color:var(--danger)}}
</style>
</head>
<body><main>
<h1>VFAT Position Report</h1>
<div class="sub">UTC · последние данные {html.escape(report.generated_at.isoformat())}</div>
<section class="panel">
<div class="controls"><label><input id="toggle-capital" type="checkbox" checked> Капитал, USD</label><label><input id="toggle-apr" type="checkbox" checked> APR net</label></div>
<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Капитал и APR по дням">
<line class="grid" x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{HEIGHT-BOTTOM}"/><line class="grid" x1="{WIDTH-RIGHT}" y1="{TOP}" x2="{WIDTH-RIGHT}" y2="{HEIGHT-BOTTOM}"/><line class="grid" x1="{LEFT}" y1="{HEIGHT-BOTTOM}" x2="{WIDTH-RIGHT}" y2="{HEIGHT-BOTTOM}"/>
<text class="axis" x="{LEFT}" y="18" data-axis="capital">Капитал, USD</text><text class="axis" x="{WIDTH-RIGHT}" y="18" text-anchor="end" data-axis="apr">APR net, %</text>
<g id="capital-series"><path class="capital" d="{capital_path}"/></g><g id="apr-series"><path class="apr" d="{apr_path}"/></g>{current_dash}{points}
</svg>
<div id="tooltip"></div>
</section>
<section class="panel">{table}</section>
<script id="chart-data" type="application/json">{chart_json}</script>
<script id="report-data" type="application/json">{report_json}</script>
<script>
const rows=JSON.parse(document.getElementById('chart-data').textContent);const tip=document.getElementById('tooltip');
document.getElementById('toggle-capital').addEventListener('change',e=>document.getElementById('capital-series').style.display=e.target.checked?'':'none');
document.getElementById('toggle-apr').addEventListener('change',e=>document.getElementById('apr-series').style.display=e.target.checked?'':'none');
document.querySelectorAll('.point').forEach(p=>{{p.addEventListener('mousemove',e=>{{const r=rows[+p.dataset.i];tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';tip.textContent=`${{r.date}}\nКапитал: ${{r.capital??'нет данных'}}\nAPR: ${{r.apr??'нет данных'}}\nGross: ${{r.claims??'нет данных'}}\nNet: ${{r.net??'нет данных'}}\nVFAT fee: ${{r.fee??'нет данных'}}\nGas account: ${{r.gas??'нет данных'}}\nКлеймов: ${{r.count}}`;}});p.addEventListener('mouseleave',()=>tip.style.display='none');}});
</script>
</main></body></html>\n"""


def _series_path(rows: list[DailyAggregate], field: str) -> str:
    values = [getattr(row, field) for row in rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return ""
    low, high = min(numeric), max(numeric)
    if low == high:
        low -= Decimal(1)
        high += Decimal(1)
    commands: list[str] = []
    drawing = False
    for index, value in enumerate(values):
        if value is None:
            drawing = False
            continue
        x = _x(index, len(rows))
        y = TOP + float((high - value) / (high - low)) * (HEIGHT - TOP - BOTTOM)
        commands.append(f"{'L' if drawing else 'M'}{x:.2f},{y:.2f}")
        drawing = True
    return " ".join(commands)


def _point_markup(rows: list[DailyAggregate]) -> str:
    markup: list[str] = []
    for index, row in enumerate(rows):
        x = _x(index, len(rows))
        markup.append(
            f'<circle class="point" data-i="{index}" cx="{x:.2f}" cy="{HEIGHT-BOTTOM}" r="8" fill="transparent" />'
        )
    return "".join(markup)


def _x(index: int, count: int) -> float:
    return LEFT + (WIDTH - LEFT - RIGHT) * (index / max(1, count - 1))


def _table(rows: tuple[DailyAggregate, ...]) -> str:
    headers = (
        "Дата UTC", "Капитал, USD", "Собрано gross, USD", "APR net",
        "Net compound, USD", "VFAT fee, USD", "Gas account, USD", "Клеймов",
        "Награды в токенах", "Статус",
    )
    head = "".join(f"<th>{item}</th>" for item in headers)
    body: list[str] = []
    for row in rows:
        rewards = ", ".join(
            f"{amount.amount.normalize():f} {html.escape(amount.symbol or amount.token_address)}"
            for amount in row.reward_amounts
        ) or "—"
        status = row.status + (" · предварительно" if row.status == "partial" else "")
        cells = (
            row.day.isoformat(), _format(row.average_capital_usd), _format(row.gross_claim_usd),
            _format(row.realized_apr_percent, "%"), _format(row.net_compound_usd),
            _format(row.automation_fee_usd), _format(row.gas_account_debit_usd),
            str(row.claim_transaction_count), rewards, status,
        )
        body.append(f'<tr class="{row.status}">' + "".join(f"<td>{html.escape(value)}</td>" for value in cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _format(value: Decimal | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value.quantize(Decimal('0.01'))}{suffix}"


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
