"""Pure reducer for the persisted frontier-question lifecycle.

The authoritative semantic source is ``docs/data/frontier_question_fsm.v1.json``.
This module deliberately owns no database, clock, history, or network effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from lakatos.verdicts import QUESTION_ANSWER_VERDICTS


class QuestionState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class QuestionEvent(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    ADJUDICATED = "ADJUDICATED"


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
    (QuestionState.CLOSED, QuestionEvent.ADJUDICATED): QuestionTransition(
        state=QuestionState.CLOSED,
        effects=(),
        transition_id="duplicate-adjudication",
    ),
}


def receipt_backed_conclusive(verdict: str | None, receipt_sha: str | None) -> bool:
    """Whether an adjudication identity can close its preregistered target.

    ``progressive`` confirms the target and ``rejected`` falsifies it; both are
    conclusive answers. Partial, equivalent, conditional, and unverified
    outcomes retain the question. This pure reducer validates the
    content-addressed receipt identity; the application service owns the
    stronger guarantee that receipt persistence and closure commit atomically.
    """

    valid_sha = (
        isinstance(receipt_sha, str)
        and len(receipt_sha) == 64
        and all(char in "0123456789abcdef" for char in receipt_sha)
    )
    return valid_sha and verdict in QUESTION_ANSWER_VERDICTS


def step(
    state: QuestionState,
    event: QuestionEvent,
    *,
    verdict: str | None = None,
    receipt_sha: str | None = None,
) -> QuestionTransition:
    """Reduce one typed event or reject without changing state.

    ``ADJUDICATED`` is Mealy-style: closure belongs to a particular
    receipt-backed verdict event rather than a stable node state.
    """

    if event is QuestionEvent.ADJUDICATED:
        if not (
            isinstance(receipt_sha, str)
            and len(receipt_sha) == 64
            and all(char in "0123456789abcdef" for char in receipt_sha)
        ):
            raise InvalidQuestionTransition(
                "ADJUDICATED requires a lowercase sha256 receipt identity; "
                "self-report cannot close a question"
            )
        if state is QuestionState.OPEN:
            if receipt_backed_conclusive(verdict, receipt_sha):
                return QuestionTransition(
                    state=QuestionState.CLOSED,
                    effects=(QuestionEffect.RECORD_CLOSURE,),
                    transition_id="adjudication-close",
                )
            return QuestionTransition(
                state=QuestionState.OPEN,
                effects=(),
                transition_id="adjudication-retain-open",
            )

    try:
        return _TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise InvalidQuestionTransition(f"invalid frontier transition: {state.value} + {event.value}") from exc
