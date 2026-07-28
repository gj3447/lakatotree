"""Pure reducer for the persisted frontier-question lifecycle.

The authoritative semantic source is ``docs/data/frontier_question_fsm.v1.json``.
This module deliberately owns no database, clock, history, or network effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QuestionState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class QuestionEvent(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class QuestionEffect(str, Enum):
    UPDATE_METADATA = "UpdateQuestionMetadata"
    RECORD_CLOSURE = "RecordQuestionClosure"


@dataclass(frozen=True)
class QuestionTransition:
    state: QuestionState
    effects: tuple[QuestionEffect, ...]
    transition_id: str

    @property
    def changed(self) -> bool:
        return bool(self.effects)


class InvalidQuestionTransition(ValueError):
    """The event has no transition from the current persisted state."""


_TRANSITIONS: dict[tuple[QuestionState, QuestionEvent], QuestionTransition] = {
    (QuestionState.OPEN, QuestionEvent.OPEN): QuestionTransition(
        state=QuestionState.OPEN,
        effects=(QuestionEffect.UPDATE_METADATA,),
        transition_id="refresh-open",
    ),
    (QuestionState.OPEN, QuestionEvent.CLOSE): QuestionTransition(
        state=QuestionState.CLOSED,
        effects=(QuestionEffect.RECORD_CLOSURE,),
        transition_id="close",
    ),
    (QuestionState.CLOSED, QuestionEvent.CLOSE): QuestionTransition(
        state=QuestionState.CLOSED,
        effects=(),
        transition_id="duplicate-close",
    ),
}


def step(state: QuestionState, event: QuestionEvent) -> QuestionTransition:
    """Reduce one typed event or reject without changing state."""

    try:
        return _TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise InvalidQuestionTransition(f"invalid frontier transition: {state.value} + {event.value}") from exc
