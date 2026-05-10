"""Phase 2 E Slice S5.5 — rule-based frontmatter merge (ADR-0027).

When a note is in conflict (mine ≠ theirs at the byte level), the
merge editor shows the **body** diff and lets the user pick hunks.
The frontmatter is decided by **rules** here, not by the user, so
mechanical churn (``updated_at``, ``schema_version``, formatter
re-flow) doesn't pollute the diff with phantom hunks. The user
already complained about this in dogfood — frontmatter sliding
into the conflict UI is by design now ruled out.

Merge rules per field — keep them small and predictable; if a
case truly needs a user decision (e.g. genuine title rename on
both sides) we surface that separately rather than smuggle it
into a body hunk.

- ``id``           — same Drive file, same id; we trust mine's.
- ``title``        — newer ``updated_at`` side wins. The
                     "both renamed differently" case is rare and
                     deferred; a subsequent slice can add a small
                     prompt for that.
- ``tags``         — set union, sorted (deduplicated).
- ``aliases``      — set union, sorted.
- ``created_at``   — earliest. The note was born at one moment;
                     whichever side records the earlier ISO is
                     closer to that truth.
- ``updated_at``   — latest. Reflects "this is the most recent
                     coordination point we know of".
- ``schema_version`` — max. Forward-compat — never downgrade.
- ``source``       — first non-empty (mine, theirs).
- ``status``       — newer ``updated_at`` side wins.
- ``trashed_from`` — first non-empty. Trash transitions are sticky.
- ``body``         — handled OUTSIDE this module; the merge editor
                     gives us the user-assembled merged body.

The output is always a valid Note (via ``Note.to_markdown``); the
serialization round-trip is tested in tests/test_frontmatter_merge.py.
"""

from __future__ import annotations

from knowlet.core.note import Note, now_iso


def merge_notes(*, mine: Note, theirs: Note, merged_body: str) -> Note:
    """Apply the rule table above and return a fresh Note ready
    to write. ``merged_body`` is the body the user assembled in
    the merge editor — kept distinct from mine.body / theirs.body
    because the user's body choice is the only "user decision"
    the merge UI surfaces.

    The id field is taken from ``mine`` because the URL the user
    operated on is a local-side handle; if the two sides really
    have different ids that's a deeper bug, surfaced upstream.

    ``updated_at`` is the max of both sides' updated_at — we do
    NOT stamp ``now_iso()`` here. The caller (the resolve-merge
    endpoint) decides whether to advance updated_at based on
    whether the user's body merge is itself a fresh edit; the
    rule layer just composes mechanical fields. (Compare to
    Vault.write_note which does stamp ``now_iso``; we let it
    own the "new edit" semantics.)
    """
    newer = _newer_by_updated_at(mine, theirs)
    return Note(
        id=mine.id,
        title=newer.title,
        body=merged_body,
        tags=sorted(set(mine.tags) | set(theirs.tags)),
        aliases=sorted(set(mine.aliases) | set(theirs.aliases)),
        created_at=min(mine.created_at, theirs.created_at) or now_iso(),
        updated_at=max(mine.updated_at, theirs.updated_at) or now_iso(),
        source=mine.source or theirs.source,
        path=mine.path,
        schema_version=max(mine.schema_version, theirs.schema_version),
        status=newer.status,
        trashed_from=mine.trashed_from or theirs.trashed_from,
    )


def _newer_by_updated_at(mine: Note, theirs: Note) -> Note:
    """ISO-8601 UTC strings emitted by ``now_iso()`` sort
    lexicographically the same as chronologically (fixed-width,
    canonical timezone), so comparing the strings is sufficient.
    Tie-breaks to mine — the local side is what the user is
    operating from."""
    if not theirs.updated_at:
        return mine
    if not mine.updated_at:
        return theirs
    return mine if mine.updated_at >= theirs.updated_at else theirs
