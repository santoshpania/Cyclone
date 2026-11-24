"""Read CSV/XLSX uploads into string rows. Every cell stays a string; typing happens in the
mapping transforms so the user sees exactly what was in the file."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass

import pandas as pd

from app.domain.normalize import fold_text

SAMPLE_ROWS = 20
_ENCODINGS = ("utf-8-sig", "cp1256", "cp1252", "latin-1")  # cp1256: Arabic Windows exports


class UnreadableFile(ValueError):
    pass


@dataclass
class Table:
    headers: list[str]
    rows: list[dict[str, str]]

    @property
    def sample(self) -> list[dict[str, str]]:
        return self.rows[:SAMPLE_ROWS]


def _dedupe_headers(raw: list[str]) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, h in enumerate(raw):
        name = str(h).strip() or f"column_{i + 1}"
        if name.lower().startswith("unnamed:"):
            name = f"column_{i + 1}"
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name} ({n + 1})")
    return out


def _frame_to_table(df: pd.DataFrame) -> Table:
    """`df` is read with header=None so pandas doesn't rename duplicate headers itself."""
    df = df.dropna(how="all")
    if df.empty:
        raise UnreadableFile("the file is empty")
    headers = _dedupe_headers(["" if pd.isna(v) else str(v) for v in df.iloc[0].tolist()])
    df = df.iloc[1:]
    df.columns = headers
    df = df.fillna("")
    rows = [{str(h): str(v).strip() for h, v in rec.items()} for rec in df.to_dict(orient="records")]
    rows = [r for r in rows if any(r.values())]
    if not headers or not rows:
        raise UnreadableFile("the file has no header row or no data rows")
    return Table(headers=headers, rows=rows)


def read_table(filename: str, data: bytes) -> Table:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            df = pd.read_excel(
                io.BytesIO(data), dtype=str, keep_default_na=False, engine="openpyxl", header=None
            )
        except Exception as exc:
            raise UnreadableFile(f"could not read spreadsheet: {exc}") from exc
        return _frame_to_table(df)
    for enc in _ENCODINGS:
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 always decodes
        raise UnreadableFile("unknown text encoding")
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    try:
        df = pd.read_csv(
            io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, skip_blank_lines=True, header=None
        )
    except Exception as exc:
        raise UnreadableFile(f"could not parse CSV: {exc}") from exc
    return _frame_to_table(df)


def header_fingerprint(headers: list[str]) -> str:
    """Same ERP export → same fingerprint, regardless of column order or header case."""
    norm = sorted(fold_text(h) for h in headers)
    return hashlib.sha256("\x1f".join(norm).encode()).hexdigest()
