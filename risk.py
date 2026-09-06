"""
Slopsquat risk scoring.

Existence is binary; risk is not. A name that does not resolve is a loud,
safe failure -- the install errors and the developer notices. The dangerous
case is a name that *does* resolve because somebody already registered it,
which a status-code check reports as fine.

This turns the metadata already fetched by registry.py into an explainable
0-100 score:

    dependency
      -> does it exist?
      -> how close is the name to something very popular? (typosquat)
      -> what does the package record look like? (age, releases, repo,
         maintainers, downloads)
      -> score, tier, and a reason for every point awarded

Three rules the scoring holds to:

1. **Explainable.** Every point carries a human-readable reason. A number
   with no reasons cannot be acted on or argued with.
2. **Unavailable is not suspicious.** npm publishes free download counts;
   PyPI does not. Scoring an absent signal as bad would systematically
   over-flag every Python package. Missing signals are reported as missing
   and contribute nothing.
3. **Triage, not proof.** A high score means "a human should look at this",
   never "this is malware".
"""

from datetime import datetime, timezone

from popular_packages import POPULAR_BY_ECOSYSTEM

MAX_SCORE = 100

TIER_THRESHOLDS = [
    (80, "CRITICAL"),
    (50, "HIGH"),
    (20, "MEDIUM"),
    (0, "LOW"),
]

# Severity ordering, so callers can express "fail at this tier or worse".
# PHANTOM sits above CRITICAL deliberately: a name that resolves to nothing
# is the one case where an install is guaranteed to either break or fetch
# whatever an attacker registers under it later.
TIER_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL", "PHANTOM"]

GATEABLE_TIERS = ["low", "medium", "high", "critical"]


def tier_rank(tier: str) -> int:
    """Position of a tier in the severity ordering; unknown tiers rank lowest."""
    try:
        return TIER_ORDER.index(tier.upper())
    except ValueError:
        return 0


def meets_threshold(tier: str, threshold: str) -> bool:
    """Whether `tier` is at least as severe as `threshold`."""
    return tier_rank(tier) >= tier_rank(threshold)


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment (Damerau-Levenshtein) distance.

    Counts a transposition of two adjacent characters as ONE edit, not two.
    That matters here specifically: swapped letters are among the most common
    typosquat techniques (`reqeusts` for `requests`, `loadsh` for `lodash`),
    and plain Levenshtein charges them double -- pushing the exact pattern
    this signal exists to catch into a lower risk band.
    """
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)

    # rows[i][j] = distance between a[:i] and b[:j]
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j

    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(
                rows[i - 1][j] + 1,          # deletion
                rows[i][j - 1] + 1,          # insertion
                rows[i - 1][j - 1] + cost,   # substitution
            )
            if (
                i > 1 and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)  # transposition

    return rows[len(a)][len(b)]


def nearest_popular_package(name: str, ecosystem: str, max_distance: int = 2):
    """The closest very-popular package name within `max_distance` edits.

    Returns (name, distance), or None. A name that is itself popular returns
    None -- `requests` is not a typosquat of `request`, they are both real.
    """
    popular = POPULAR_BY_ECOSYSTEM.get(ecosystem, set())
    normalized = name.lower().lstrip("@")
    if normalized in popular:
        return None

    best = None
    for candidate in popular:
        # Length gap alone exceeds the budget; skip the O(n*m) comparison.
        if abs(len(candidate) - len(normalized)) > max_distance:
            continue
        distance = edit_distance(normalized, candidate)
        if distance <= max_distance and (best is None or distance < best[1]):
            best = (candidate, distance)
    return best


def _age_days(first_release: str | None) -> int | None:
    if not first_release:
        return None
    try:
        released = datetime.fromisoformat(first_release.replace("Z", "+00:00"))
    except ValueError:
        return None
    if released.tzinfo is None:
        released = released.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - released).days


def _signal(name, points, reason):
    return {"signal": name, "points": points, "reason": reason}


def _age_signal(metadata):
    days = _age_days(metadata.get("first_release"))
    if days is None:
        return None, "age"

    if days < 30:
        return _signal("age", 30, f"first published {days} days ago"), None
    if days < 90:
        return _signal("age", 20, f"first published {days} days ago"), None
    if days < 365:
        return _signal("age", 10, f"first published {days} days ago"), None
    return None, None


def _release_signal(metadata):
    count = metadata.get("release_count")
    if count is None:
        return None, "releases"
    if count == 1:
        return _signal("releases", 15, "only one release ever published"), None
    if count <= 3:
        return _signal("releases", 8, f"only {count} releases published"), None
    return None, None


def _repository_signal(metadata):
    if metadata.get("repository_url"):
        return None, None
    return _signal("repository", 15, "no repository or homepage link"), None


def _description_signal(metadata):
    description = (metadata.get("description") or "").strip()
    if not description:
        return _signal("description", 10, "no description"), None
    if len(description) < 15:
        return _signal("description", 5, f"description is only {len(description)} characters"), None
    return None, None


def _maintainer_signal(metadata):
    count = metadata.get("maintainer_count")
    if count is None:
        return None, "maintainers"
    if count == 0:
        return _signal("maintainers", 15, "no listed maintainers"), None
    if count == 1:
        return _signal("maintainers", 5, "a single maintainer"), None
    return None, None


def _downloads_signal(metadata):
    downloads = metadata.get("weekly_downloads")
    if downloads is None:
        return None, "downloads"
    if downloads < 50:
        return _signal("downloads", 25, f"{downloads} downloads last week"), None
    if downloads < 1000:
        return _signal("downloads", 15, f"{downloads} downloads last week"), None
    if downloads < 10000:
        return _signal("downloads", 5, f"{downloads:,} downloads last week"), None
    return None, None


def _typosquat_signal(name, ecosystem):
    nearest = nearest_popular_package(name, ecosystem)
    if not nearest:
        return None, None
    target, distance = nearest
    points = 30 if distance == 1 else 15
    return _signal(
        "typosquat",
        points,
        f"{distance} edit{'s' if distance > 1 else ''} away from '{target}'",
    ), None


_METADATA_SIGNALS = (
    _age_signal,
    _release_signal,
    _repository_signal,
    _description_signal,
    _maintainer_signal,
    _downloads_signal,
)


def tier_for(score: int) -> str:
    for threshold, tier in TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return "LOW"


def score_package(metadata: dict) -> dict:
    """Score one package from its registry metadata (see registry.fetch_metadata)."""
    name = metadata["name"]
    ecosystem = metadata["ecosystem"]

    typosquat, _ = _typosquat_signal(name, ecosystem)

    if not metadata.get("exists"):
        # Not a live threat today -- the install simply fails. But the name is
        # an unclaimed squatting target, and if somebody registers it this
        # becomes a real, silent compromise. Reported as its own tier rather
        # than folded into the numeric scale.
        signals = [_signal("existence", MAX_SCORE, "does not exist on the registry")]
        if typosquat:
            signals.append(typosquat)
        return {
            "name": name,
            "ecosystem": ecosystem,
            "exists": False,
            "score": MAX_SCORE,
            "tier": "PHANTOM",
            "signals": signals,
            "unavailable_signals": [],
        }

    signals = []
    unavailable = []

    if typosquat:
        signals.append(typosquat)

    for signal_fn in _METADATA_SIGNALS:
        signal, missing = signal_fn(metadata)
        if signal:
            signals.append(signal)
        if missing:
            unavailable.append(missing)

    score = min(MAX_SCORE, sum(s["points"] for s in signals))

    return {
        "name": name,
        "ecosystem": ecosystem,
        "exists": True,
        "score": score,
        "tier": tier_for(score),
        "signals": signals,
        "unavailable_signals": unavailable,
    }
