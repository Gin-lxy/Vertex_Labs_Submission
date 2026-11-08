from datetime import datetime, timezone


def deals_needing_followup(deals, today=None):
    """Return names of open deals with no contact in the last 14 days,
    most stale first. Timestamps are normalised to UTC, so mixed
    offsets are handled correctly."""
    today = today or datetime.now(timezone.utc)
    result = []
    for deal in deals:
        if deal["stage"].startswith("Closed"):
            continue
        if deal["last_contact"] is None:
            last = datetime.min
        else:
            last = datetime.fromisoformat(deal["last_contact"])
        if (today - last).days > 14:
            result.append(deal)
    result.sort(key=lambda d: d["last_contact"] or "")
    return [d["name"] for d in result]
