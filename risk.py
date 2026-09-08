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
# UNVERIFIED is deliberately absent. It is not a point on this scale at all
# -- it means the registry could not be asked -- so meets_threshold rejects
# it outright rather than ranking it. Ranking it as 0 would have made it
# satisfy `--fail-on low`, since LOW is itself rank 0.
TIER_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL", "PHANTOM"]

GATEABLE_TIERS = ["low", "medium", "high", "critical"]


def tier_rank(tier: str) -> int:
    """Position of a tier in the severity ordering; unknown tiers rank lowest."""
    try:
        return TIER_ORDER.index(tier.upper())
    except ValueError:
        return 0


def meets_threshold(tier: str, threshold: str) -> bool:
    """Whether `tier` is at least as severe as `threshold`.

    A tier outside the severity scale (UNVERIFIED) is never severe enough
    for any gate: it carries no claim about the package to be severe about.
    """
    if tier.upper() not in TIER_ORDER:
        return False
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


# ---------------------------------------------------------------------------
# Confidence
#
# Risk and confidence answer different questions. Risk asks how suspicious a
# package looks; confidence asks how much evidence that judgement rests on. A
# package can be risk 90 / confidence 40 (alarming pattern, thin evidence) or
# risk 10 / confidence 100 (ordinary package, everything known).
#
# This is deliberately *evidence completeness*, not "probability the verdict
# is correct". There is no calibration data behind this tool, so a number
# implying otherwise would be an unearned claim. The weights below say how
# much each piece of evidence contributes, they sum to 100, and the whole
# calculation is a sum -- no tuning, no model.
# ---------------------------------------------------------------------------

EVIDENCE_WEIGHTS = {
    # Dominant by design: without a registry answer, nothing else is known.
    "registry_lookup": 40,
    "release_history": 15,
    "download_stats": 15,
    "maintainer_info": 15,
    "repository_info": 10,
    "description": 5,
}

# A definitive "no such package" is nearly all the evidence there is to have,
# even though a nonexistent package publishes no metadata to corroborate it.
# Not 100: registries are briefly inconsistent, and an unclaimed name can be
# registered a minute after the check.
PHANTOM_CONFIDENCE = 95

# Identity uncertainty is not evidence about the package -- it is doubt about
# *which* package is being judged, which undercuts the whole assessment.
RESOLUTION_PENALTIES = {
    "unresolved": 25,
    "ambiguous": 25,
}
# A registry-identity match means a distribution of that name exists, not
# that it is what provides the module.
REGISTRY_IDENTITY_PENALTY = 5


def _evidence_item(name: str, available: bool, detail: str) -> dict:
    return {
        "name": name,
        "available": available,
        "weight": EVIDENCE_WEIGHTS[name],
        "detail": detail,
    }


def score_confidence(metadata: dict, resolution: dict | None = None) -> dict:
    """How much evidence backs the risk verdict, 0-100, with the reasons."""
    lookup_ok = metadata.get("lookup_ok", metadata.get("exists") is not None)

    if not lookup_ok:
        evidence = [_evidence_item(
            "registry_lookup", False, "registry could not be reached"
        )]
        return _confidence_result(0, evidence, resolution)

    evidence = [_evidence_item("registry_lookup", True, "registry answered")]

    if metadata.get("exists") is False:
        return _confidence_result(PHANTOM_CONFIDENCE, evidence, resolution)

    for name, value, present, absent in [
        ("release_history", metadata.get("release_count"),
         "release history available", "no release history"),
        ("download_stats", metadata.get("weekly_downloads"),
         "download statistics available",
         "download statistics unavailable for this registry"),
        ("maintainer_info", metadata.get("maintainer_count"),
         "maintainer information available",
         "maintainer information unavailable for this registry"),
        ("repository_info", metadata.get("repository_url"),
         "repository link present", "no repository link"),
        ("description", metadata.get("description"),
         "description present", "no description"),
    ]:
        evidence.append(_evidence_item(
            name, value is not None, present if value is not None else absent
        ))

    total = sum(item["weight"] for item in evidence if item["available"])
    return _confidence_result(total, evidence, resolution)


def _confidence_result(base: int, evidence: list[dict],
                       resolution: dict | None) -> dict:
    penalty = 0
    note = None

    if resolution:
        status = resolution.get("resolution_status")
        if status in RESOLUTION_PENALTIES:
            penalty = RESOLUTION_PENALTIES[status]
            note = f"import identity {status}"
        elif resolution.get("resolution_source") == "registry":
            penalty = REGISTRY_IDENTITY_PENALTY
            note = "import identity inferred from the registry, not a known mapping"

    confidence = max(0, min(100, base - penalty))
    return {
        "confidence": confidence,
        "evidence": evidence,
        "confidence_penalty": penalty,
        "confidence_note": note,
    }


def score_package(metadata: dict, resolution: dict | None = None) -> dict:
    """Score one package from its registry metadata (see registry.fetch_metadata).

    `resolution` is the import-reconciliation result, when the package was
    reached via a source import. It never changes the risk score -- only how
    confident we are that the right package is being scored.
    """
    name = metadata["name"]
    ecosystem = metadata["ecosystem"]

    typosquat, _ = _typosquat_signal(name, ecosystem)
    confidence = score_confidence(metadata, resolution)

    if metadata.get("exists") is None:
        # The registry could not be consulted. This is not a finding about
        # the package -- reporting it as one would turn an outage into a
        # scan full of accusations.
        return {
            "name": name,
            "ecosystem": ecosystem,
            "exists": None,
            "score": 0,
            "tier": "UNVERIFIED",
            "signals": [],
            "unavailable_signals": ["registry_lookup"],
            **confidence,
        }

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
            **confidence,
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
        **confidence,
    }
