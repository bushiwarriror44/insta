"""The briefs a fresh install starts with.

Each says what to make *and* what to avoid, because that is what makes
the difference in practice: running the agent against a local model
showed that "calm nature" alone returns three versions of the same shot,
while naming the exclusions and the variety wanted does not.

They are seeded once, when the library is empty, and are plain rows
afterwards. Emptying the library brings them back, which is the simplest
"reset to defaults" there is.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PromptPreset

BUILT_IN: list[tuple[str, str]] = [
    (
        "Calm nature",
        "Misty forests, mountain ridges and quiet water at dawn. Slow drone "
        "moves and long static holds, soft low light, natural colour. "
        "Vary the subject and the camera move between posts. "
        "No people, no buildings, no on-screen text.",
    ),
    (
        "Slow food",
        "Close macro shots of cooking: steam off a pan, dough being folded, "
        "a knife through fruit. Warm kitchen light, shallow depth of field, "
        "unhurried movement. Hands only. "
        "No faces, no branded packaging, no on-screen text.",
    ),
    (
        "City at night",
        "Rain-slick streets, neon reflections in puddles, headlights passing. "
        "Slow tracking moves and long lenses, deep shadows, saturated colour. "
        "No recognisable faces, no readable shop signs or logos.",
    ),
    (
        "Ocean and coast",
        "Waves breaking, tide pools, sea cliffs and foam at golden hour. "
        "Mix aerial views with close water textures so the batch is not all "
        "one scale. Natural sound implied, no music cues. "
        "No people, no boats, no on-screen text.",
    ),
    (
        "Desk and craft",
        "Hands working with tools, wood, clay or paper. Warm lamp light, "
        "shallow depth of field, small deliberate movements. Vary the "
        "material between posts. "
        "No faces, no brand names, no on-screen text.",
    ),
    (
        "Abstract textures",
        "Ink diffusing in water, sand shifting, light bending through glass, "
        "paint mixing. Macro framing, slow motion, strong colour contrast. "
        "Each post a different material. "
        "No recognisable objects, no people, no text.",
    ),
]


def seed_if_empty(session: Session) -> int:
    """Fill an empty library. Returns how many were added."""
    count = session.execute(select(func.count(PromptPreset.id))).scalar_one()
    if count:
        return 0

    session.add_all(PromptPreset(name=name, brief=brief) for name, brief in BUILT_IN)
    session.commit()
    return len(BUILT_IN)
