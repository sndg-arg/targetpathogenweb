import re
import urllib.error
import urllib.request
from dataclasses import dataclass


GO_BASIC_OBO_URL = "https://current.geneontology.org/ontology/go-basic.obo"
GO_BASIC_OBO_FALLBACK_URLS = (
    GO_BASIC_OBO_URL,
    "https://release.geneontology.org/latest/ontology/go-basic.obo",
)
GO_DOWNLOAD_HEADERS = {
    "User-Agent": "targetpathogenweb/1.0 (+https://github.com/sndg-arg/targetpathogenweb)",
    "Accept": "text/plain, text/*;q=0.9, */*;q=0.8",
}

_QUOTED_TEXT_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class GOTermRecord:
    identifier: str
    name: str
    definition: str
    is_obsolete: bool
    alt_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GOResolvedTerm:
    identifier: str
    canonical_id: str
    name: str
    definition: str
    is_obsolete: bool


def download_go_obo(url=GO_BASIC_OBO_URL, timeout=60):
    urls = [str(url or "").strip()] if str(url or "").strip() else []
    for fallback in GO_BASIC_OBO_FALLBACK_URLS:
        if fallback not in urls:
            urls.append(fallback)

    last_error = None
    for candidate in urls:
        request = urllib.request.Request(candidate, headers=GO_DOWNLOAD_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("No GO ontology download URL was available")


def _parse_obo_quoted_value(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return ""
    match = _QUOTED_TEXT_RE.match(value)
    if not match:
        return value
    return bytes(match.group(1), "utf-8").decode("unicode_escape").strip()


def parse_go_obo(text):
    records = []
    stanza_type = None
    current = None

    def flush():
        nonlocal current
        if stanza_type != "Term" or not current:
            current = None
            return

        identifier = str(current.get("id") or "").strip()
        if not identifier.startswith("GO:"):
            current = None
            return

        name = str(current.get("name") or identifier).strip()
        definition = _parse_obo_quoted_value(current.get("def"))
        alt_ids = tuple(
            alt_id
            for alt_id in current.get("alt_ids", [])
            if str(alt_id or "").strip().startswith("GO:")
        )
        records.append(
            GOTermRecord(
                identifier=identifier,
                name=name,
                definition=definition,
                is_obsolete=bool(current.get("is_obsolete")),
                alt_ids=alt_ids,
            )
        )
        current = None

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("!"):
            continue
        if line == "[Term]":
            flush()
            stanza_type = "Term"
            current = {"alt_ids": []}
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            stanza_type = line[1:-1]
            current = None
            continue
        if stanza_type != "Term" or current is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "id":
            current["id"] = value
        elif key == "name":
            current["name"] = value
        elif key == "def":
            current["def"] = value
        elif key == "alt_id":
            current["alt_ids"].append(value)
        elif key == "is_obsolete":
            current["is_obsolete"] = value.lower() == "true"

    flush()
    return records


def expand_go_records(records):
    resolved = []
    seen_ids = set()

    for record in records:
        primary = GOResolvedTerm(
            identifier=record.identifier,
            canonical_id=record.identifier,
            name=record.name,
            definition=record.definition,
            is_obsolete=record.is_obsolete,
        )
        if primary.identifier not in seen_ids:
            resolved.append(primary)
            seen_ids.add(primary.identifier)

        for alt_id in record.alt_ids:
            alt_term = GOResolvedTerm(
                identifier=alt_id,
                canonical_id=record.identifier,
                name=record.name,
                definition=record.definition,
                is_obsolete=True,
            )
            if alt_term.identifier not in seen_ids:
                resolved.append(alt_term)
                seen_ids.add(alt_term.identifier)

    return resolved
