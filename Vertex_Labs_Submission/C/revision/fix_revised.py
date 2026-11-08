"""Follow-up selection using explicit UTC and input-validation rules."""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone


OPEN_STAGES = frozenset({'Sourcing', 'Diligence'})
CLOSED_STAGES = frozenset({'Closed - Won', 'Closed - Lost'})
FOLLOWUP_INTERVAL = timedelta(hours=336)


def _deal_label(deal, index):
    if isinstance(deal, Mapping):
        identifier = deal.get('id')
        if identifier is not None and (not isinstance(identifier, str) or identifier.strip()):
            return f'deal id={identifier!r}'
        name = deal.get('name')
        if isinstance(name, str) and name.strip():
            return f'deal name={name!r}'
    return f'deal index={index}'


def _as_utc(value, field, label):
    if not isinstance(value, datetime):
        raise ValueError(f'{label}: {field} must be a timezone-aware datetime')
    try:
        offset = value.utcoffset()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label}: {field} has an invalid timezone ({exc})') from exc
    if offset is None:
        raise ValueError(f'{label}: {field} must include an explicit timezone')
    try:
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label}: {field} cannot be converted to UTC ({exc})') from exc


def deals_needing_followup(deals, today=None):
    """Return due open-deal names, with never-contacted deals first.

    A contact is due at an elapsed UTC interval of at least 336 hours.
    None means no contact history. Both groups retain input order for
    equal contact times. Invalid open records raise a contextual ValueError.
    Closed records skip contact validation; global today is validated first.
    """
    try:
        records = list(deals)
    except TypeError as exc:
        raise ValueError('deal <input>: deals must be an iterable of records') from exc
    context = _deal_label(records[0], 0) if records else 'deal <empty-input>'
    reference = datetime.now(timezone.utc) if today is None else today
    now_utc = _as_utc(reference, 'today', context)

    never_contacted = []
    stale = []
    for index, deal in enumerate(records):
        label = _deal_label(deal, index)
        if not isinstance(deal, Mapping):
            raise ValueError(f'{label}: record must be a mapping')
        stage = deal.get('stage')
        if not isinstance(stage, str) or stage not in OPEN_STAGES | CLOSED_STAGES:
            raise ValueError(f'{label}: unknown stage {stage!r}')
        if stage in CLOSED_STAGES:
            continue

        name = deal.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'{label}: name must be a nonempty string')
        if 'last_contact' not in deal:
            raise ValueError(f'{label}: last_contact field is required; None means no contact history')
        contact = deal['last_contact']
        if contact is None:
            never_contacted.append(name)
            continue
        if not isinstance(contact, str):
            raise ValueError(f'{label}: last_contact must be an ISO datetime string or None')
        try:
            parsed = datetime.fromisoformat(contact)
        except ValueError as exc:
            raise ValueError(f'{label}: last_contact has invalid ISO datetime format ({exc})') from exc
        last_utc = _as_utc(parsed, 'last_contact', label)
        if last_utc > now_utc:
            raise ValueError(
                f'{label}: last_contact is in the future '
                f'({last_utc.isoformat()} > today {now_utc.isoformat()})'
            )
        if now_utc - last_utc >= FOLLOWUP_INTERVAL:
            stale.append((last_utc, name))

    stale.sort(key=lambda item: item[0])
    return never_contacted + [name for _, name in stale]
