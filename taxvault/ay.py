"""Assessment Year computation (Section 7). India's Financial Year runs April 1 - March 31;
the AY label is always computed at runtime from the current date, never stored or manually set.

Section 7's own worked example (Apr 1 2026 - Mar 31 2027 -> AY 2026-27) doesn't match the
literal formula text in the locked spec, which has an off-by-one shift. This implements the
corrected formula that reproduces the spec's own example, per explicit confirmation."""

from django.utils import timezone


def current_assessment_year(as_of=None):
    """Returns the current AY as e.g. "2026-27". `as_of` (a date) is only for testing
    specific boundary dates — normal callers omit it and get today's date."""
    as_of = as_of or timezone.localdate()
    start_year = as_of.year if as_of.month >= 4 else as_of.year - 1
    end_year_short = (start_year + 1) % 100
    return f"{start_year}-{end_year_short:02d}"
