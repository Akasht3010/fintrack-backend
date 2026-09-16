from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

# Every money field is validated and stored as Decimal (exact arithmetic —
# see the NUMERIC(12,2) columns in app/models/) but Pydantic v2 serializes a
# bare Decimal field to a JSON *string* by default, which would silently
# change the wire contract every frontend numeric consumer (charts, budget
# math, sorting, CSV) already relies on. This keeps Decimal internally and
# only overrides serialization for JSON responses, back to a plain number.
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
