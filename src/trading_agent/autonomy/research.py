"""Sanitized immutable read view. No owner issuer, renewal, SQL or executor handle."""

from typing import Literal

from ..supervised.contracts import Record
from .contracts import Champion, Envelope


class ResearchView(Record):
    envelope: Envelope
    champion: Champion
    authority: Literal["LIVE_NOT_AUTHORIZED"] = "LIVE_NOT_AUTHORIZED"
    authority_mutations_available: Literal[False] = False
