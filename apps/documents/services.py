import hashlib
import re
from typing import Iterable


def calculate_file_checksum(file_field) -> str:
    if not file_field:
        return ""

    hasher = hashlib.sha256()
    file_handle = file_field.open("rb")
    try:
        for chunk in iter(lambda: file_handle.read(8192), b""):
            hasher.update(chunk)
    finally:
        file_handle.close()
    return hasher.hexdigest()


def extract_reference_candidates(text: str) -> dict:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return {}

    patterns = {
        "official_receipt_numbers": r"\b(?:OR|OFFICIAL\s+RECEIPT)\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*([A-Z0-9/-]{4,})",
        "atp_numbers": r"\bATP\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*([A-Z0-9/-]{4,})",
        "registration_numbers": r"\bREG(?:ISTRATION)?\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*([A-Z0-9/-]{4,})",
        "practitioner_numbers": r"\bP(?:RACTITIONER)?\s*#?\s*[:#-]?\s*([A-Z0-9/-]{4,})",
        "license_numbers": r"\bLIC(?:ENCE|ENSE)?\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*([A-Z0-9/-]{4,})",
        "years": r"\b(19\d{2}|20\d{2})\b",
    }

    extracted = {}
    for key, pattern in patterns.items():
        matches = re.findall(pattern, cleaned, flags=re.IGNORECASE)
        normalized = []
        for match in matches:
            value = match.strip().upper()
            if value and value not in normalized:
                normalized.append(value)
        if normalized:
            extracted[key] = normalized[:10]
    return extracted


def document_matches_query(document, query: str) -> bool:
    query = " ".join((query or "").strip().lower().split())
    if not query:
        return True

    haystacks = [
        getattr(document, "title", ""),
        getattr(document, "description", ""),
    ]

    metadata = getattr(document, "metadata", {}) or {}
    haystacks.extend(str(value) for value in metadata.values())

    current_version = getattr(document, "current_version", None)
    if current_version:
        haystacks.append(getattr(current_version, "original_filename", ""))
        haystacks.append(getattr(current_version, "extracted_text", ""))

    flattened = " ".join(str(item or "").lower() for item in haystacks)
    return query in flattened


def duplicate_checksums(documents: Iterable) -> dict:
    checksum_map = {}
    for document in documents:
        version = getattr(document, "current_version", None)
        checksum = getattr(version, "checksum", "") if version else ""
        if not checksum:
            continue
        checksum_map.setdefault(checksum, []).append(document.id)

    return {
        checksum: document_ids
        for checksum, document_ids in checksum_map.items()
        if len(document_ids) > 1
    }
