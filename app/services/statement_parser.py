"""
Bank statement parsing (HDFC NetBanking downloads, for now).

HDFC offers the statement as "Delimited" text (comma-separated, padded
columns) or "Excel" (legacy .xls). Both are the same table — Date,
Narration, Chq./Ref.No., Value Dt, Withdrawal Amt., Deposit Amt., Closing
Balance — under a block of account details, followed by a summary. Rather
than hard-coding row offsets (which shift with address length, etc.) the
header row is found by its column names and every format is read into the
same grid of strings first.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


class StatementFormatError(ValueError):
    """The file isn't a statement this parser understands."""


@dataclass
class StatementRow:
    date: date
    narration: str
    reference: Optional[str]
    debit: Decimal
    credit: Decimal
    closing_balance: Optional[Decimal]


@dataclass
class ParsedStatement:
    bank: str
    account_last4: Optional[str]
    rows: list[StatementRow]


@dataclass
class NarrationDetails:
    merchant: str
    payment_method: str  # upi | card | netbanking | atm | autopay | other
    reference: Optional[str]
    category: Optional[str]  # "transfer" / "interest" / "salary" when the narration says so


# --- grid reading -----------------------------------------------------------

def _grid_from_text(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig", errors="replace")
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]


def _grid_from_xls(content: bytes) -> list[list[str]]:
    import xlrd  # only needed for Excel uploads

    try:
        book = xlrd.open_workbook(file_contents=content)
    except Exception as exc:
        raise StatementFormatError("Couldn't open this Excel file") from exc
    sheet = book.sheet_by_index(0)
    grid = []
    for r in range(sheet.nrows):
        row = []
        for c in range(sheet.ncols):
            cell = sheet.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                row.append(xlrd.xldate_as_datetime(cell.value, book.datemode).strftime("%d/%m/%Y"))
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                value = cell.value
                row.append(str(int(value)) if float(value).is_integer() and abs(value) > 1e9 else repr(value))
            else:
                row.append(str(cell.value).strip())
        grid.append(row)
    return grid


def _read_grid(content: bytes, filename: str) -> list[list[str]]:
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or filename.lower().endswith(".xls"):
        return _grid_from_xls(content)
    if content[:2] == b"PK" or filename.lower().endswith(".xlsx"):
        raise StatementFormatError("Save the statement as .xls (HDFC's Excel option) or Delimited text, not .xlsx")
    if content[:4] == b"%PDF":
        raise StatementFormatError("PDF statements aren't supported yet — download it as Excel or Delimited instead")
    return _grid_from_text(content)


# --- table location ---------------------------------------------------------

_COLUMN_KEYS = {
    "date": lambda h: h.startswith("date") or h == "txn date" or h == "transaction date",
    "narration": lambda h: "narration" in h or h in ("description", "particulars"),
    "reference": lambda h: "ref" in h or "chq" in h,
    "debit": lambda h: "withdrawal" in h or h.startswith("debit"),
    "credit": lambda h: "deposit" in h or h.startswith("credit"),
    "balance": lambda h: "balance" in h,
}


def _find_header(grid: list[list[str]]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(grid):
        lowered = [cell.lower().strip() for cell in row]
        if not any("narration" in c or c in ("description", "particulars") for c in lowered):
            continue
        columns: dict[str, int] = {}
        for key, matches in _COLUMN_KEYS.items():
            for col, header in enumerate(lowered):
                if header and col not in columns.values() and matches(header):
                    columns[key] = col
                    break
        if {"date", "narration", "debit", "credit"} <= columns.keys():
            return index, columns
    raise StatementFormatError("Couldn't find the transaction table — is this an HDFC account statement?")


_ACCOUNT_NO = re.compile(r"\bAccount\s*(?:No|Number)\.?\s*:?\s*([0-9][0-9 ]{5,})", re.IGNORECASE)


def _account_last4(grid: list[list[str]], header_index: int) -> Optional[str]:
    for row in grid[:header_index]:
        for cell in row:
            match = _ACCOUNT_NO.search(cell)
            if match:
                digits = re.sub(r"\D", "", match.group(1))
                return digits[-4:] if len(digits) >= 4 else None
    return None


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Optional[Decimal]:
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _cell(row: list[str], col: Optional[int]) -> str:
    return row[col] if col is not None and col < len(row) else ""


def _clean_reference(raw: str) -> Optional[str]:
    digits = raw.strip().lstrip("0")
    return digits if len(digits) >= 6 else None


def parse_hdfc_statement(content: bytes, filename: str) -> ParsedStatement:
    grid = _read_grid(content, filename)
    header_index, columns = _find_header(grid)

    rows: list[StatementRow] = []
    for raw in grid[header_index + 1:]:
        if any("statement summary" in cell.lower() for cell in raw):
            break
        when = _parse_date(_cell(raw, columns["date"]))
        narration = _cell(raw, columns["narration"])
        if when is None:
            # A wrapped narration continues on the next line with no date.
            if rows and narration and not narration.startswith("*"):
                rows[-1].narration = f"{rows[-1].narration} {narration}".strip()
            continue
        debit = _parse_amount(_cell(raw, columns["debit"]))
        credit = _parse_amount(_cell(raw, columns["credit"]))
        balance = _parse_amount(_cell(raw, columns.get("balance"))) if "balance" in columns else None
        if debit is None or credit is None or (debit == 0 and credit == 0):
            continue
        rows.append(StatementRow(
            date=when,
            narration=narration,
            reference=_clean_reference(_cell(raw, columns.get("reference"))),
            debit=debit,
            credit=credit,
            closing_balance=balance,
        ))

    if not rows:
        raise StatementFormatError("No transactions found in this statement")
    return ParsedStatement(bank="HDFC", account_last4=_account_last4(grid, header_index), rows=rows)


# --- narration -> payee / method -------------------------------------------

_UPI_REF = re.compile(r"\b(\d{12})\b")
_CARD_MASK = re.compile(r"\b\d{4,6}X+\d{4}\b", re.IGNORECASE)


def _tidy(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" -/")
    return name.title() if name.isupper() else name


def describe_narration(narration: str) -> NarrationDetails:
    n = narration.strip()
    upper = n.upper()
    parts = [p.strip() for p in n.split("-")]

    if re.search(r"\bCC\s*0*\d*X*\d*\s*AUTOPAY|CREDIT\s*CARD|\bCC\s+PAYMENT|\bCRED\b", upper):
        return NarrationDetails(_tidy(parts[1] if upper.startswith("UPI-") and len(parts) > 1 else "Credit card bill"),
                                "upi" if upper.startswith("UPI") else "autopay", _ref(n), "transfer")

    if upper.startswith("UPI"):
        # UPI-<payee name>-<vpa>-<ifsc>-<12-digit ref>-<note>
        name = parts[1] if len(parts) > 1 and parts[1] else "UPI payment"
        return NarrationDetails(_tidy(name), "upi", _ref(n), None)

    if upper.startswith(("ATW", "NWD", "EAW", "ATM")):
        return NarrationDetails("ATM withdrawal", "atm", None, None)

    if upper.startswith(("POS", "ME DC", "IN DC", "ECOM", "PCD")):
        rest = _CARD_MASK.split(n, maxsplit=1)
        name = rest[1] if len(rest) > 1 else re.sub(r"^(POS|ME DC|IN DC|ECOM|PCD)\s*", "", n, flags=re.IGNORECASE)
        return NarrationDetails(_tidy(name.split("-")[0]) or "Card payment", "card", None, None)

    if upper.startswith(("ACH", "NACH")) or re.search(r"\b(SI|E-?MANDATE|AUTOPAY)\b", upper):
        name = re.sub(r"^N?ACH\s*[DC]?\s*-\s*", "", n, flags=re.IGNORECASE).split("-")[0]
        name = re.sub(r"^TP ACH\s*", "", name, flags=re.IGNORECASE)
        return NarrationDetails(_tidy(name) or "Autopay", "autopay", None, None)

    if upper.startswith(("NEFT", "IMPS", "RTGS")) or "FUND TRF" in upper or "FT -" in upper:
        # NEFT CR-<ifsc>-<name>-..., IMPS-<ref>-<name>-...
        name = parts[2] if len(parts) > 2 else parts[-1]
        category = "salary" if "SALARY" in upper else "transfer"
        return NarrationDetails(_tidy(name) or "Bank transfer", "netbanking", _ref(n), category)

    if "INTEREST" in upper:
        return NarrationDetails("Interest", "other", None, "interest")

    return NarrationDetails(_tidy(n[:60]) or "Bank transaction", "other", None, None)


def _ref(narration: str) -> Optional[str]:
    match = _UPI_REF.search(narration)
    return match.group(1) if match else None
