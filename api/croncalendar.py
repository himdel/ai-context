"""Translate the cron syntax accepted by contexts into platform calendars."""

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


def _cron_fields(expression):
    fields = expression.strip().split(None, 5)
    if not fields:
        raise CronCalendarError("empty cron expression")
    if fields[0].startswith("@"):
        raise CronCalendarError(f"unsupported cron macro: {fields[0]}")
    if len(fields) != 5:
        raise CronCalendarError("calendar backend needs a five-field cron expression")

    return (
        _field(fields[0], 0, 59, {}, "minute"),
        _field(fields[1], 0, 23, {}, "hour"),
        _field(fields[2], 1, 31, {}, "day of month"),
        _field(fields[3], 1, 12, MONTHS, "month"),
        _field(fields[4], 0, 7, DAYS, "day of week"),
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
    minute, hour, dom, month, dow = _cron_fields(expression)

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


def launchd_intervals(expression):
    """Return launchd StartCalendarInterval dictionaries for a cron value."""

    fields = expression.strip().split(None, 5)
    if not fields:
        raise CronCalendarError("empty cron expression")
    if fields[0].startswith("@"):
        if len(fields) != 1 or fields[0] not in MACROS:
            raise CronCalendarError(f"unsupported cron macro: {fields[0]}")
        macro = fields[0]
        if macro in ("@yearly", "@annually"):
            return [{"Month": 1, "Day": 1, "Hour": 0, "Minute": 0}]
        if macro == "@monthly":
            return [{"Day": 1, "Hour": 0, "Minute": 0}]
        if macro == "@weekly":
            return [{"Weekday": 0, "Hour": 0, "Minute": 0}]
        if macro in ("@daily", "@midnight"):
            return [{"Hour": 0, "Minute": 0}]
        return [{"Minute": 0}]

    minute, hour, dom, month, dow = _cron_fields(expression)
    all_minutes = minute == set(range(60))
    all_hours = hour == set(range(24))
    all_months = month == set(range(1, 13))
    all_days = dom == set(range(1, 32))
    all_weekdays = dow == set(range(0, 7))

    # Cron treats restricted day-of-month and day-of-week fields as an OR.
    # launchd combines fields with AND, so use two interval branches.
    if all_days and all_weekdays:
        day_options = [{}]
    elif all_days:
        day_options = [{"Weekday": value} for value in sorted(dow)]
    elif all_weekdays:
        day_options = [{"Day": value} for value in sorted(dom)]
    else:
        day_options = [{"Day": value} for value in sorted(dom)]
        day_options += [{"Weekday": value} for value in sorted(dow)]

    minute_options = [None] if all_minutes else sorted(minute)
    hour_options = [None] if all_hours else sorted(hour)
    month_options = [None] if all_months else sorted(month)

    # Avoid relying on an empty interval dictionary for every-minute jobs.
    if all_minutes and all_hours and all_months and day_options == [{}]:
        minute_options = list(range(60))

    interval_count = (
        len(minute_options) * len(hour_options) * len(month_options) * len(day_options)
    )
    if interval_count > 4096:
        raise CronCalendarError(
            "launchd schedule expands to too many calendar intervals; "
            "use a simpler schedule or the Contexts process backend"
        )

    intervals = []
    for minute_value in minute_options:
        for hour_value in hour_options:
            for month_value in month_options:
                for day_option in day_options:
                    interval = dict(day_option)
                    if minute_value is not None:
                        interval["Minute"] = minute_value
                    if hour_value is not None:
                        interval["Hour"] = hour_value
                    if month_value is not None:
                        interval["Month"] = month_value
                    intervals.append(interval)
    return intervals
