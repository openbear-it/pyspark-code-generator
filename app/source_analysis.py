import csv
import io
import json
from datetime import datetime
from pathlib import Path

from app.schemas import ContextFile

SAMPLE_SIZE = 5


def infer_type(values: list[str]) -> str:
    normalized = [value.strip() for value in values if value.strip()]
    if not normalized:
        return "unknown"
    if all(value.lower() in {"true", "false"} for value in normalized):
        return "boolean"
    try:
        for value in normalized:
            int(value)
        return "integer"
    except ValueError:
        pass
    try:
        for value in normalized:
            float(value)
        return "number"
    except ValueError:
        pass
    try:
        for value in normalized:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "datetime"
    except ValueError:
        return "string"


def summarize_records(name: str, source_format: str, records: list[dict[str, object]]) -> str:
    columns = list(dict.fromkeys(column for record in records for column in record))
    if not columns:
        return f"Source: {name}. Detected format: {source_format}. No columns were found."
    schema = []
    for column in columns:
        values = ["" if record.get(column) is None else str(record.get(column)) for record in records]
        missing = sum(not value.strip() for value in values)
        schema.append(f"{column}: {infer_type(values)} ({missing} missing)")
    sample = json.dumps(records[:SAMPLE_SIZE], ensure_ascii=False, default=str)
    return (
        f"Source: {name}. Detected format: {source_format}. Rows analyzed: {len(records)}. "
        f"Columns ({len(columns)}): {', '.join(schema)}. Sample records: {sample}"
    )


def analyze_source(name: str, content: bytes) -> ContextFile:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{name} is not UTF-8 text") from error

    extension = Path(name).suffix.lower()
    if extension in {".csv", ".tsv"}:
        delimiter = "\t" if extension == ".tsv" else ","
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            pass
        records = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        return ContextFile(name=name, content="", analysis=summarize_records(name, "delimited text", records))
    if extension in {".json", ".jsonl", ".ndjson"}:
        try:
            if extension == ".json":
                parsed = json.loads(text)
                records = parsed if isinstance(parsed, list) else [parsed]
            else:
                records = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as error:
            raise ValueError(f"{name} is not valid JSON") from error
        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"{name} must contain JSON objects to be structurally analyzed")
        return ContextFile(name=name, content="", analysis=summarize_records(name, "JSON", records))

    line_count = text.count("\n") + (1 if text else 0)
    return ContextFile(
        name=name,
        content=text,
        analysis=f"Source: {name}. Detected format: UTF-8 text. Lines: {line_count}. Bytes: {len(content)}.",
    )