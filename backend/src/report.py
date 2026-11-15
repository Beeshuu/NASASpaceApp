"""Weekly health report for one astronaut, in plain language. Pure Python (no Workers imports) so tests run under CPython."""

from datetime import datetime, timezone

STEADY = 0.05  # a first-to-last-day change under 5% reads as steady


def _day(ms):
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return f"{d.day} {d:%b}"


def _trend(first, last):
    if first == 0 or abs(last - first) / abs(first) < STEADY:
        return "steady"
    return "up" if last > first else "down"


def weekly_report(entity_id, start_ms, end_ms, daily, alerts, checkins, labels):
    """Markdown. `daily`: [{day, domain, metric, avg, n}]; `alerts`: [{severity, message, fired_ts}] in the window;
    `checkins`: days with a check-in; `labels`: "domain/metric" -> (label, unit)."""
    lines = [f"# Weekly health report: {entity_id}", "", f"{_day(start_ms)} to {_day(end_ms)} (mission time).", ""]
    lines.append(f"You completed your daily check-in on {checkins} of 7 days.")
    series = {}
    for row in sorted(daily, key=lambda r: r["day"]):
        series.setdefault(f'{row["domain"]}/{row["metric"]}', []).append(row["avg"])
    lines += ["", "## How your readings looked", ""]
    for key, vals in sorted(series.items()):
        label, unit = labels.get(key, (key.split("/")[1].replace("_", " ").capitalize(), ""))
        mean = sum(vals) / len(vals)
        lines.append(f"- {label}: averaged {mean:.1f}{' ' + unit if unit else ''}, {_trend(vals[0], vals[-1])} over the week.")
    if not series:
        lines.append("No readings were recorded this week.")
    lines += ["", "## Alerts", ""]
    if alerts:
        lines += [f"- {_day(a['fired_ts'])}, {a['severity']}: {a['message']}" for a in sorted(alerts, key=lambda a: a["fired_ts"])]
    else:
        lines.append("No alerts this week.")
    return "\n".join(lines) + "\n"
