"""Translate the cron syntax accepted by contexts into systemd calendars."""

from __future__ import annotations


class CronCalendarError(ValueError):
    pass


MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
DAYS = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
MACROS = {
    "@yearly": ("*-01-01 00:00:00",),
    "@annually": ("*-01-01 00:00:00",),
    "@monthly": ("*-*-01 00:00:00",),
    "@weekly": ("Sun *-*-* 00:00:00",),
    "@daily": ("*-*-* 00:00:00",),
    "@midnight": ("*-*-* 00:00:00",),
    "@hourly": ("*-*-* *:00:00",),
}


def _number(value, names, field):
    try:
        return int(value)
    except ValueError:
        try:
            return names[value.upper()]
        except KeyError as exc:
            raise CronCalendarError(f"invalid {field} value: {value}") from exc


def _field(value, low, high, names, field):
    if value == "?" or any(char in value for char in "LW#"):
        raise CronCalendarError(f"unsupported {field} syntax: {value}")
    result = set()
    for part in value.split(","):
        if not part:
            raise CronCalendarError(f"empty {field} list item")
        base, separator, step_text = part.partition("/")
        if separator:
            try:
                step = int(step_text)
            except ValueError as exc:
                raise CronCalendarError(f"invalid {field} step: {step_text}") from exc
            if step < 1:
                raise CronCalendarError(f"{field} step must be positive")
        else:
            step = 1

        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start = _number(start_text, names, field)
            end = _number(end_text, names, field)
        else:
            if separator:
                raise CronCalendarError(f"{field} steps need '*' or a range")
            start = end = _number(base, names, field)

        if start < low or end > high or start > end:
            raise CronCalendarError(f"{field} value outside {low}-{high}: {part}")
        result.update(range(start, end + 1, step))

    if field == "day of week" and 7 in result:
        result.remove(7)
        result.add(0)
    return result


def _values(values, low, high, width=0):
    if values == set(range(low, high + 1)):
        return "*"
    return ",".join(str(value).zfill(width) for value in sorted(values))


def _day_names(values):
    return ",".join(
        next(name.title() for name, number in DAYS.items() if number == value)
        for value in sorted(values)
    )


def calendar_expressions(expression):
    """Return exact systemd calendar expressions for a five-field cron value."""
    fields = expression.strip().split(None, 5)
    if not fields:
        raise CronCalendarError("empty cron expression")
    if fields[0].startswith("@"):
        if fields[0] == "@reboot":
            raise CronCalendarError("@reboot is not a calendar schedule")
        if len(fields) != 1 or fields[0] not in MACROS:
            raise CronCalendarError(f"unsupported cron macro: {fields[0]}")
        return MACROS[fields[0]]
    if len(fields) != 5:
        raise CronCalendarError("systemd backend needs a five-field cron expression")

    minute = _field(fields[0], 0, 59, {}, "minute")
    hour = _field(fields[1], 0, 23, {}, "hour")
    dom = _field(fields[2], 1, 31, {}, "day of month")
    month = _field(fields[3], 1, 12, MONTHS, "month")
    dow = _field(fields[4], 0, 7, DAYS, "day of week")

    time = f"{_values(hour, 0, 23, 2)}:{_values(minute, 0, 59, 2)}:00"
    month_text = _values(month, 1, 12, 2)
    dom_text = _values(dom, 1, 31, 2)
    date_any = f"*-{month_text}-*"
    date_dom = f"*-{month_text}-{dom_text}"
    all_dom = dom == set(range(1, 32))
    all_dow = dow == set(range(0, 7))

    if all_dom and all_dow:
        return (f"{date_any} {time}",)
    if all_dom:
        return (f"{_day_names(dow)} {date_any} {time}",)
    if all_dow:
        return (f"{date_dom} {time}",)

    # Cron's restricted DOM and DOW fields are an OR; systemd calendar fields
    # are an AND, so represent the two branches as separate events.
    return (
        f"{date_dom} {time}",
        f"{_day_names(dow)} {date_any} {time}",
    )
