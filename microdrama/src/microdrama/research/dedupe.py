"""Deterministic dedupe and theme mining for research (T009).

No embeddings and no model calls: everything is exact-token statistics over the untrusted
text, so the same inputs always produce the same clusters. Public comments are qualitative
clues (SPEC §7): clustering only counts and samples them, it never treats them as market
shares or instructions.

Limitation (recorded in evidence/T009.md): theme keys are ASCII ``[a-z0-9_]`` tokens and
bigrams, so Latin-script themes work while Thai text yields no theme keys; real Thai theme
segmentation is T010 / T031 evidence, not this module's claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from microdrama.contracts.hashing import sha256_hex
from microdrama.research.models import CommentCluster, CommentIn, ThemeCluster

_WORD = re.compile(r"\w+", re.UNICODE)
_THEME_KEY = re.compile(r"^[a-z0-9_]+$")

# Small English stopword list: enough to keep fixture/generic filler out of the theme table.
_STOPWORDS = frozenset(
    """a an and are as at be been but by can did do for from had has have he her him his i if in
    into is it its me my no not of on or our out over said she so some such than that the their
    them then there these they this to too us was we were what when which who will with would
    you your real source synthetic fixture excerpt""".split()
)

MIN_THEME_TOKEN_LENGTH = 3


def normalize_text(text: str) -> str:
    """Casefolded, whitespace-collapsed comparison form of untrusted text."""
    return " ".join(text.casefold().split())


def word_tokens(text: str, *, keep_short: bool = False) -> list[str]:
    """Unicode word tokens in order. Short/stop tokens are dropped unless ``keep_short``."""
    tokens = _WORD.findall(normalize_text(text))
    if keep_short:
        return tokens
    return [t for t in tokens if len(t) >= MIN_THEME_TOKEN_LENGTH and t not in _STOPWORDS]


def token_set(text: str) -> frozenset[str]:
    return frozenset(word_tokens(text, keep_short=True))


def jaccard_bp(a: frozenset[str], b: frozenset[str]) -> int:
    """Jaccard similarity in basis points (0..10000); 0 for two empty sets."""
    union = a | b
    if not union:
        return 0
    return round(10_000 * len(a & b) / len(union))


@dataclass(frozen=True)
class DedupeConfig:
    comment_jaccard_bp: int = 8_000
    theme_min_distinct_sources: int = 2
    max_themes: int = 12


def cluster_comments(comments: list[CommentIn], config: DedupeConfig) -> list[CommentCluster]:
    """Collapse near-duplicate comments (same normalized text, or token-set similarity at or
    above the threshold). Deterministic: members are visited in (text, author) order and a
    comment joins the first cluster it matches, so ordering never depends on dict order."""
    threshold = config.comment_jaccard_bp
    prepared = sorted(
        ((normalize_text(c.text), c.author_ref, c.text, token_set(c.text)) for c in comments),
        key=lambda item: (item[0], item[1]),
    )
    clusters: list[list[tuple[str, str, str, frozenset[str]]]] = []
    for item in prepared:
        for cluster in clusters:
            representative = cluster[0]
            if item[0] == representative[0] or jaccard_bp(item[3], representative[3]) >= threshold:
                cluster.append(item)
                break
        else:
            clusters.append([item])
    out: list[CommentCluster] = []
    for cluster in clusters:
        key = sha256_hex("\n".join(sorted({m[0] for m in cluster})).encode("utf-8"))
        longest = max(cluster, key=lambda m: len(m[2]))[2]
        out.append(
            CommentCluster(
                cluster_key=key,
                representative_text=longest[:5000],
                size=len(cluster),
                distinct_authors=len({m[1] for m in cluster}),
                sample_author_refs=sorted({m[1] for m in cluster})[:5],
            )
        )
    return sorted(out, key=lambda c: (-c.size, c.cluster_key))


def extract_themes(documents: list[tuple[str, str]], config: DedupeConfig) -> list[ThemeCluster]:
    """Mine themes from ``(source_id, excerpt)`` pairs.

    A theme is an ASCII unigram or bigram that appears (case-insensitively) in at least
    ``theme_min_distinct_sources`` distinct sources. Themes are ranked by distinct-source
    support, then raw occurrences, then key, and capped at ``max_themes``. Thai and other
    non-Latin scripts produce no theme keys here (see the module limitation note).
    """
    counted: dict[str, dict[str, int]] = {}
    for source_id, excerpt in documents:
        tokens = [t for t in word_tokens(excerpt) if _THEME_KEY.fullmatch(t)]
        bigrams = [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for key in {*tokens, *bigrams}:
            counted.setdefault(key, {}).setdefault(source_id, 0)
            counted[key][source_id] += (tokens + bigrams).count(key)

    candidates: list[ThemeCluster] = []
    for key, mentions in sorted(counted.items()):
        if len(mentions) < config.theme_min_distinct_sources:
            continue
        candidates.append(
            ThemeCluster(
                theme_key=key,
                label=key.replace("_", " "),
                distinct_sources=len(mentions),
                occurrences=sum(mentions.values()),
                source_ids=sorted(mentions),
            )
        )
    ranked = sorted(candidates, key=lambda c: (-c.distinct_sources, -c.occurrences, c.theme_key))
    return ranked[: config.max_themes]


__all__ = [
    "DedupeConfig",
    "cluster_comments",
    "extract_themes",
    "jaccard_bp",
    "normalize_text",
    "token_set",
    "word_tokens",
]
