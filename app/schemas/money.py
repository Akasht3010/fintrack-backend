from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

# Every money field is validated and stored as Decimal (exact arithmetic —
# see the NUMERIC(12,2) columns in app/models/). Serialized as a JSON
# *string* (Pydantic v2's own default for a bare Decimal field, made
# explicit here) rather than a number: a JSON number is a float on every
# consumer (JS included), so serializing this way was quietly handing every
# client a lossy value and inviting client-side float arithmetic on it — see
# test_money_precision.py and the frontend's Money helpers, which now parse
# this string with a decimal library instead of doing `+`/`-`/`/` on it
# directly. `str(Decimal)` never uses scientific notation for the magnitudes
# this app deals with, so this round-trips exactly.
#
# max_digits/decimal_places mirror NUMERIC(12,2): without them a value like
# 0.001 passes a `gt=0` check and is then silently rounded to 0.00 by the
# database, and anything past 10 integer digits fails as a DB error (500)
# rather than a validation error (422).
Money = Annotated[
    Decimal,
    Field(max_digits=12, decimal_places=2),
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]
