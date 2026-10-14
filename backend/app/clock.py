from datetime import UTC, datetime


def get_now() -> datetime:
    """The current instant, timezone-aware in UTC.

    Read once per request and passed to services, so tests can inject a fixed
    clock instead of depending on the machine's time or timezone.
    """
    return datetime.now(UTC)
