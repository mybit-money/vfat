from __future__ import annotations

import html
import json
from decimal import Decimal
from typing import Callable

from .contracts import DailyAggregate, Report, report_to_dict


WIDTH = 960
HEIGHT = 390
LEFT = 88
RIGHT = 88
TOP = 42
BOTTOM = 78
PLOT_BOTTOM = HEIGHT - BOTTOM
PLOT_WIDTH = WIDTH - LEFT - RIGHT
PLOT_HEIGHT = PLOT_BOTTOM - TOP
TICK_COUNT = 5


def render_html(report: Report) -> str:
    chronological = list(reversed(report.days))
    chart_rows = [
        {
            "date": row.day.isoformat(),
            "capital": _number(row.average_capital_usd),
            "apr": _number(row.realized_apr_percent),
            "cumulativePnl": _number(row.cumulative_pnl_usd),
            "dailyPnl": _number(row.daily_pnl_usd),
            "positionValue": _number(row.position_value_usd),
            "positionChange": _number(row.daily_position_value_change_usd),
            "netClaim": _number(row.net_claim_usd),
            "cumulativePnlEstimated": row.cumulative_pnl_is_estimated,
            "dailyPnlEstimated": row.daily_pnl_is_estimated,
            "positionValueEstimated": row.position_value_is_estimated,
            "positionChangeEstimated": row.daily_position_value_change_is_estimated,
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
    table = _table(report.days)
    capital_chart = _capital_apr_chart(chronological)
    pnl_chart = _pnl_chart(chronological)
    claims_chart = _claims_chart(chronological)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VFAT Position Report</title>
<style>
:root{{--bg:#0d1321;--panel:#151e30;--grid:#33415c;--text:#edf2f4;--muted:#9fb0c8;--capital:#5dd39e;--apr:#ffca3a;--pnl:#63b3ff;--position:#b794f4;--claim:#4fd1c5;--positive:#48c78e;--negative:#ff6b6b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:24px}}h1{{margin:0 0 6px}}h2{{font-size:16px;margin:0 0 12px}}.sub{{color:var(--muted);margin-bottom:20px}}
.panel{{background:var(--panel);border-radius:14px;padding:18px;margin-bottom:18px;overflow:auto}}
.controls{{display:flex;flex-wrap:wrap;gap:18px;margin-bottom:10px}}label{{cursor:pointer}}svg{{min-width:760px;width:100%;height:auto}}
.grid{{stroke:var(--grid);stroke-width:1}}.axis{{fill:var(--muted);font-size:11px}}.axis-title{{fill:var(--muted);font-size:12px}}
.capital{{fill:none;stroke:var(--capital);stroke-width:3}}.apr{{fill:none;stroke:var(--apr);stroke-width:3}}.cumulative-pnl{{fill:none;stroke:var(--pnl);stroke-width:3}}
.bar.positive{{fill:var(--positive)}}.bar.negative{{fill:var(--negative)}}.average{{fill:none;stroke-width:1.5;stroke-dasharray:7 5;opacity:.9}}
.bar.position-change{{opacity:.72;stroke:var(--position);stroke-width:1.5}}.bar.net-claim{{fill:var(--claim)}}[data-estimated="true"]{{stroke:#fff;stroke-width:1.5;stroke-dasharray:4 3}}
.average-label{{font-size:11px;font-weight:600}}.current-marker{{stroke:var(--muted);opacity:.55}}.hover-guide{{stroke:#fff;opacity:0;pointer-events:none}}
.hover-target{{fill:transparent;cursor:crosshair}}
#tooltip{{position:fixed;display:none;z-index:10;pointer-events:none;background:#05080f;border:1px solid var(--grid);padding:9px;border-radius:8px;white-space:pre-line}}
table{{border-collapse:collapse;width:100%;min-width:1180px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-last-child(2),td:nth-last-child(2),th:last-child,td:last-child{{text-align:left}}tr.partial td:last-child{{color:var(--apr)}}tr.unreliable td:last-child{{color:var(--negative)}}
</style>
</head>
<body><main>
<h1>VFAT Position Report</h1>
<div class="sub">UTC · последние данные {html.escape(report.generated_at.isoformat())}</div>
<section class="panel">
<h2>Капитал и APR</h2>
<div class="controls">
<label><input id="toggle-capital" type="checkbox" checked> Капитал, USD</label>
<label><input id="toggle-apr" type="checkbox" checked> APR net</label>
</div>
{capital_chart}
</section>
<section class="panel">
<h2>PnL портфеля</h2>
<div class="controls">
<label><input id="toggle-cumulative-pnl" type="checkbox" checked> Накопленный PnL</label>
<label><input id="toggle-daily-pnl" type="checkbox" checked> Дневной PnL</label>
<label><input id="toggle-position-change" type="checkbox" checked> Δ стоимости позиций</label>
</div>
{pnl_chart}
</section>
<section class="panel">
<h2>Чистые claims</h2>
<div class="controls">
<label><input id="toggle-net-claim" type="checkbox" checked> Claim после VFAT fee и gas account</label>
</div>
{claims_chart}
</section>
<section class="panel">{table}</section>
<div id="tooltip"></div>
<script id="chart-data" type="application/json">{chart_json}</script>
<script id="report-data" type="application/json">{report_json}</script>
<script>
const rows=JSON.parse(document.getElementById('chart-data').textContent);
const tip=document.getElementById('tooltip');
const toggles={{
  'toggle-capital':['capital-series','capital-average'],
  'toggle-apr':['apr-series','apr-average'],
  'toggle-cumulative-pnl':['cumulative-pnl-series','cumulative-pnl-average'],
  'toggle-daily-pnl':['daily-pnl-series','daily-pnl-average'],
  'toggle-position-change':['position-change-series','position-change-average'],
  'toggle-net-claim':['net-claim-series','net-claim-average']
}};
Object.entries(toggles).forEach(([toggle,groups])=>document.getElementById(toggle).addEventListener('change',e=>groups.forEach(id=>document.getElementById(id).style.display=e.target.checked?'':'none')));
document.querySelectorAll('.hover-target').forEach(target=>{{
  target.addEventListener('mousemove',event=>{{
    const row=rows[+target.dataset.i];
    document.querySelectorAll('.hover-guide').forEach(guide=>{{guide.setAttribute('x1',target.dataset.x);guide.setAttribute('x2',target.dataset.x);guide.style.opacity='.7';}});
    tip.style.display='block';tip.style.left=(event.clientX+12)+'px';tip.style.top=(event.clientY+12)+'px';
    tip.textContent=`${{row.date}}\nСтоимость позиций: ${{estimatedMoney(row.positionValue,row.positionValueEstimated)}}\nΔ стоимости: ${{estimatedMoney(row.positionChange,row.positionChangeEstimated)}}\nPnL накопленный: ${{estimatedMoney(row.cumulativePnl,row.cumulativePnlEstimated)}}\nPnL за день: ${{estimatedMoney(row.dailyPnl,row.dailyPnlEstimated)}}\nЧистый claim: ${{money(row.netClaim)}}\nКапитал средний: ${{money(row.capital)}}\nAPR: ${{value(row.apr,'%')}}\nGross: ${{money(row.claims)}}\nNet compound: ${{money(row.net)}}\nVFAT fee: ${{money(row.fee)}}\nGas account: ${{money(row.gas)}}\nКлеймов: ${{row.count}}`;
  }});
  target.addEventListener('mouseleave',()=>{{tip.style.display='none';document.querySelectorAll('.hover-guide').forEach(guide=>guide.style.opacity='0');}});
}});
function money(value){{return value==null?'нет данных':'$'+value.toFixed(2)}}
function estimatedMoney(value,estimated){{return (estimated?'≈ ':'')+money(value)+(estimated?' (оценка)':'')}}
function value(number,suffix){{return number==null?'нет данных':number.toFixed(2)+suffix}}
</script>
</main></body></html>\n"""


def _capital_apr_chart(rows: list[DailyAggregate]) -> str:
    capital = [row.average_capital_usd for row in rows]
    apr = [row.realized_apr_percent for row in rows]
    capital_scale = _scale(capital)
    apr_scale = _scale(apr)
    capital_path = _series_path(capital, capital_scale)
    apr_path = _series_path(apr, apr_scale)
    capital_average = _completed_average(rows, "average_capital_usd")
    apr_average = _completed_average(rows, "realized_apr_percent")
    return f"""<svg data-chart="capital-apr" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Капитал и APR по дням">
{_grid_and_axes(rows, capital_scale, apr_scale, "Капитал, USD", "APR net, %", "capital", "apr")}
<g id="capital-series"><path class="capital" d="{capital_path}"/></g>
<g id="apr-series"><path class="apr" d="{apr_path}"/></g>
<g id="capital-average">{_average_markup(capital_average, capital_scale, "capital", "var(--capital)", "Средний капитал", "$")}</g>
<g id="apr-average">{_average_markup(apr_average, apr_scale, "apr", "var(--apr)", "Средний APR", "%", right=True)}</g>
{_interaction_markup(rows)}
</svg>"""


def _pnl_chart(rows: list[DailyAggregate]) -> str:
    cumulative = [row.cumulative_pnl_usd for row in rows]
    daily = [row.daily_pnl_usd for row in rows]
    position_change = [row.daily_position_value_change_usd for row in rows]
    cumulative_scale = _scale(cumulative)
    daily_scale = _scale(daily + position_change, include_zero=True)
    cumulative_path = _series_path(cumulative, cumulative_scale)
    cumulative_average = _completed_average(rows, "cumulative_pnl_usd")
    daily_average = _completed_average(rows, "daily_pnl_usd")
    position_average = _completed_average(rows, "daily_position_value_change_usd")
    pnl_estimated = [row.daily_pnl_is_estimated for row in rows]
    value_estimated = [row.daily_position_value_change_is_estimated for row in rows]
    bars = _bar_markup(daily, daily_scale, offset=-0.55, estimated=pnl_estimated)
    position_bars = _bar_markup(
        position_change,
        daily_scale,
        extra_class="position-change",
        offset=0.55,
        estimated=value_estimated,
    )
    return f"""<svg data-chart="pnl" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Накопленный и дневной PnL">
{_grid_and_axes(rows, cumulative_scale, daily_scale, "PnL накопленный, USD", "Дневные изменения, USD", "cumulative-pnl", "daily-pnl")}
<g id="daily-pnl-series">{bars}</g>
<g id="position-change-series">{position_bars}</g>
<g id="cumulative-pnl-series"><path class="cumulative-pnl" d="{cumulative_path}"/></g>
<g id="cumulative-pnl-average">{_average_markup(cumulative_average, cumulative_scale, "cumulative-pnl", "var(--pnl)", "Средний накопленный PnL", "$")}</g>
<g id="daily-pnl-average">{_average_markup(daily_average, daily_scale, "daily-pnl", "var(--positive)", "Средний дневной PnL", "$", right=True)}</g>
<g id="position-change-average">{_average_markup(position_average, daily_scale, "position-change", "var(--position)", "Среднее Δ стоимости", "$", right=True)}</g>
{_interaction_markup(rows)}
</svg>"""


def _claims_chart(rows: list[DailyAggregate]) -> str:
    claims = [row.net_claim_usd for row in rows]
    scale = _scale(claims, include_zero=True)
    average = _completed_average(rows, "net_claim_usd")
    bars = _bar_markup(claims, scale, extra_class="net-claim")
    return f"""<svg data-chart="claims" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Чистые claims по дням">
{_grid_and_axes(rows, scale, scale, "Чистый claim, USD", "Чистый claim, USD", "net-claim", "net-claim")}
<g id="net-claim-series">{bars}</g>
<g id="net-claim-average">{_average_markup(average, scale, "net-claim", "var(--claim)", "Средний чистый claim", "$")}</g>
{_interaction_markup(rows)}
</svg>"""


def _grid_and_axes(
    rows: list[DailyAggregate],
    left_scale: tuple[Decimal, Decimal],
    right_scale: tuple[Decimal, Decimal],
    left_title: str,
    right_title: str,
    left_axis: str | None = None,
    right_axis: str | None = None,
) -> str:
    left_attr = f' data-axis="{left_axis}"' if left_axis else ""
    right_attr = f' data-axis="{right_axis}"' if right_axis else ""
    parts = [
        f'<text class="axis-title"{left_attr} x="{LEFT}" y="20">{html.escape(left_title)}</text>',
        f'<text class="axis-title"{right_attr} x="{WIDTH-RIGHT}" y="20" text-anchor="end">{html.escape(right_title)}</text>',
        f'<line class="grid" x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{PLOT_BOTTOM}"/>',
        f'<line class="grid" x1="{WIDTH-RIGHT}" y1="{TOP}" x2="{WIDTH-RIGHT}" y2="{PLOT_BOTTOM}"/>',
    ]
    left_ticks = _ticks(left_scale)
    right_ticks = _ticks(right_scale)
    for index, (left_value, right_value) in enumerate(zip(left_ticks, right_ticks)):
        y = TOP + PLOT_HEIGHT * index / (TICK_COUNT - 1)
        parts.append(f'<line class="grid" x1="{LEFT}" y1="{y:.2f}" x2="{WIDTH-RIGHT}" y2="{y:.2f}"/>')
        parts.append(f'<text class="axis" x="{LEFT-8}" y="{y+4:.2f}" text-anchor="end">{_compact(left_value)}</text>')
        parts.append(f'<text class="axis" x="{WIDTH-RIGHT+8}" y="{y+4:.2f}">{_compact(right_value)}</text>')
    for index, row in enumerate(rows):
        x = _x(index, len(rows))
        parts.append(
            f'<text class="axis" data-axis="date" x="{x:.2f}" y="{PLOT_BOTTOM+20}" '
            f'text-anchor="end" transform="rotate(-45 {x:.2f} {PLOT_BOTTOM+20})">{row.day.strftime("%d.%m")}</text>'
        )
    return "".join(parts)


def _scale(values: list[Decimal | None], *, include_zero: bool = False) -> tuple[Decimal, Decimal]:
    numeric = [value for value in values if value is not None]
    if include_zero:
        numeric.append(Decimal(0))
    if not numeric:
        return Decimal(0), Decimal(1)
    low, high = min(numeric), max(numeric)
    if low == high:
        padding = max(abs(low) * Decimal("0.05"), Decimal(1))
    else:
        padding = (high - low) * Decimal("0.08")
    return low - padding, high + padding


def _ticks(scale: tuple[Decimal, Decimal]) -> list[Decimal]:
    low, high = scale
    return [high - (high - low) * Decimal(index) / Decimal(TICK_COUNT - 1) for index in range(TICK_COUNT)]


def _y(value: Decimal, scale: tuple[Decimal, Decimal]) -> float:
    low, high = scale
    return TOP + float((high - value) / (high - low)) * PLOT_HEIGHT


def _series_path(values: list[Decimal | None], scale: tuple[Decimal, Decimal]) -> str:
    commands: list[str] = []
    drawing = False
    for index, value in enumerate(values):
        if value is None:
            drawing = False
            continue
        commands.append(f"{'L' if drawing else 'M'}{_x(index, len(values)):.2f},{_y(value, scale):.2f}")
        drawing = True
    return " ".join(commands)


def _bar_markup(
    values: list[Decimal | None],
    scale: tuple[Decimal, Decimal],
    *,
    extra_class: str = "",
    offset: float = 0.0,
    estimated: list[bool] | None = None,
) -> str:
    zero_y = _y(Decimal(0), scale)
    width = min(22.0, PLOT_WIDTH / max(1, len(values)) * 0.34)
    bars: list[str] = []
    for index, value in enumerate(values):
        if value is None:
            continue
        value_y = _y(value, scale)
        top = min(zero_y, value_y)
        height = max(1.0, abs(zero_y - value_y))
        kind = "positive" if value >= 0 else "negative"
        class_name = f"bar {kind}" + (f" {extra_class}" if extra_class else "")
        estimate_attr = (
            ' data-estimated="true"'
            if estimated is not None and estimated[index]
            else ""
        )
        bars.append(
            f'<rect class="{class_name}"{estimate_attr} '
            f'x="{_x(index, len(values))+offset*width-width/2:.2f}" y="{top:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" rx="2"/>'
        )
    return "".join(bars)


def _completed_average(rows: list[DailyAggregate], field: str) -> Decimal | None:
    values = [
        getattr(row, field)
        for row in rows
        if row.status != "partial" and getattr(row, field) is not None
    ]
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def _average_markup(
    value: Decimal | None,
    scale: tuple[Decimal, Decimal],
    name: str,
    color: str,
    label: str,
    suffix: str,
    *,
    right: bool = False,
) -> str:
    if value is None:
        return ""
    y = _y(value, scale)
    anchor = "end" if right else "start"
    x = WIDTH - RIGHT - 6 if right else LEFT + 6
    shown = f"{suffix}{_compact(value)}" if suffix == "$" else f"{_compact(value)}{suffix}"
    return (
        f'<line class="average" data-average="{name}" x1="{LEFT}" y1="{y:.2f}" '
        f'x2="{WIDTH-RIGHT}" y2="{y:.2f}" stroke="{color}"/>'
        f'<text class="average-label" x="{x}" y="{y-5:.2f}" text-anchor="{anchor}" '
        f'fill="{color}">{html.escape(label)}: {shown}</text>'
    )


def _interaction_markup(rows: list[DailyAggregate]) -> str:
    if not rows:
        return ""
    band = PLOT_WIDTH / max(1, len(rows))
    targets: list[str] = [
        f'<line class="hover-guide" x1="{LEFT}" y1="{TOP}" x2="{LEFT}" y2="{PLOT_BOTTOM}"/>'
    ]
    if rows[-1].status == "partial":
        x = _x(len(rows) - 1, len(rows))
        targets.append(
            f'<line class="current-marker" x1="{x:.2f}" y1="{TOP}" x2="{x:.2f}" '
            f'y2="{PLOT_BOTTOM}" stroke-dasharray="7 5"/>'
        )
    for index in range(len(rows)):
        x = _x(index, len(rows))
        start = max(LEFT, x - band / 2)
        targets.append(
            f'<rect class="hover-target" data-i="{index}" data-x="{x:.2f}" '
            f'x="{start:.2f}" y="{TOP}" width="{band:.2f}" height="{PLOT_HEIGHT}"/>'
        )
    return "".join(targets)


def _x(index: int, count: int) -> float:
    return LEFT + PLOT_WIDTH * (index / max(1, count - 1))


def _table(rows: tuple[DailyAggregate, ...]) -> str:
    headers = (
        "Дата UTC", "Капитал, USD", "Собрано gross, USD", "APR net",
        "Net compound, USD", "VFAT fee, USD", "Gas account, USD", "Клеймов",
        "Стоимость позиций, USD", "Δ стоимости, USD", "PnL накопленный, USD",
        "PnL за день, USD", "Чистый claim, USD", "Награды в токенах", "Статус",
    )
    head = "".join(f"<th>{item}</th>" for item in headers)
    body: list[str] = []
    for row in rows:
        rewards = ", ".join(
            f"{amount.amount.normalize()} {html.escape(amount.symbol or amount.token_address)}"
            for amount in row.reward_amounts
        ) or "—"
        estimates = []
        if row.cumulative_pnl_is_estimated or row.daily_pnl_is_estimated:
            estimates.append("PnL")
        if (
            row.position_value_is_estimated
            or row.daily_position_value_change_is_estimated
        ):
            estimates.append("стоимость")
        status = row.status + (" · предварительно" if row.status == "partial" else "")
        if estimates:
            status += " · оценка: " + ", ".join(estimates)
        cells = (
            row.day.isoformat(), _format(row.average_capital_usd),
            _format(row.gross_claim_usd), _format(row.realized_apr_percent, "%"),
            _format(row.net_compound_usd), _format(row.automation_fee_usd),
            _format(row.gas_account_debit_usd), str(row.claim_transaction_count),
            _format(row.position_value_usd, estimated=row.position_value_is_estimated),
            _format(
                row.daily_position_value_change_usd,
                estimated=row.daily_position_value_change_is_estimated,
            ),
            _format(
                row.cumulative_pnl_usd,
                estimated=row.cumulative_pnl_is_estimated,
            ),
            _format(row.daily_pnl_usd, estimated=row.daily_pnl_is_estimated),
            _format(row.net_claim_usd),
            rewards, status,
        )
        body.append(f'<tr class="{row.status}">' + "".join(f"<td>{html.escape(value)}</td>" for value in cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _format(value: Decimal | None, suffix: str = "", *, estimated: bool = False) -> str:
    if value is None:
        return "—"
    prefix = "≈ " if estimated else ""
    return f"{prefix}{value.quantize(Decimal('0.01'))}{suffix}"


def _compact(value: Decimal) -> str:
    absolute = abs(value)
    if absolute >= Decimal("1000000"):
        return f"{value / Decimal('1000000'):.1f}M"
    if absolute >= Decimal("1000"):
        return f"{value / Decimal('1000'):.1f}k"
    if absolute >= Decimal("100"):
        return f"{value:.0f}"
    return f"{value:.2f}"


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
