"""
Attachment / file analysis utilities.

Classifies attachments by extension and MIME type and flags
potentially dangerous file types.
"""

from __future__ import annotations

import mimetypes
import os

# ── High-risk file categories ─────────────────────────────────────────────
EXECUTABLE_EXTENSIONS: set[str] = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1",
    ".psm1", ".psd1", ".reg", ".hta",
}

SCRIPT_EXTENSIONS: set[str] = {
    ".sh", ".bash", ".zsh", ".fish", ".py", ".pl", ".rb",
    ".php", ".asp", ".aspx", ".jar", ".class",
}

MACRO_DOCUMENT_EXTENSIONS: set[str] = {
    ".doc", ".dot", ".xls", ".xlt", ".ppt", ".pot",   # legacy Office (macro-capable)
    ".docm", ".dotm", ".xlsm", ".xltm", ".pptm", ".potm",
    ".xlam", ".ppam",
}

ARCHIVE_EXTENSIONS: set[str] = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".cab",
    ".iso", ".img",
}

# MIME types that are inherently risky
RISKY_MIME_PREFIXES: set[str] = {
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-sh",
    "application/x-executable",
    "application/x-java-archive",
}


def analyze_attachment(attachment: dict) -> dict:
    """
    Analyze a single attachment dict and return an AttachmentAnalysis-compatible dict.

    Expected input keys (all optional except 'filename'):
        filename   : original file name
        mime_type  : MIME type string (guessed if absent)
        size_bytes : integer file size
        content    : raw bytes or None (not used for static analysis)
    """
    filename: str = attachment.get("filename", "unknown")
    size_bytes: int | None = attachment.get("size_bytes")
    provided_mime: str = attachment.get("mime_type", "")

    _, ext = os.path.splitext(filename.lower())
    guessed_mime, _ = mimetypes.guess_type(filename)
    mime_type = provided_mime or guessed_mime or "application/octet-stream"

    reasons: list[str] = []
    suspicious = False

    # ── Extension checks ─────────────────────────────────────────────────────
    if ext in EXECUTABLE_EXTENSIONS:
        reasons.append(f"Executable file type: {ext}")
        suspicious = True

    elif ext in SCRIPT_EXTENSIONS:
        reasons.append(f"Script file type: {ext}")
        suspicious = True

    elif ext in MACRO_DOCUMENT_EXTENSIONS:
        reasons.append(
            f"Office document with potential macro support: {ext}"
        )
        suspicious = True

    elif ext in ARCHIVE_EXTENSIONS:
        reasons.append(f"Archive file — contents unknown: {ext}")
        # Archives are suspicious but not always malicious
        suspicious = True

    # ── MIME type checks ─────────────────────────────────────────────────────
    for risky in RISKY_MIME_PREFIXES:
        if mime_type.startswith(risky):
            reasons.append(f"Risky MIME type: {mime_type}")
            suspicious = True
            break

    # ── Extension / MIME mismatch ─────────────────────────────────────────────
    if guessed_mime and provided_mime and guessed_mime != provided_mime:
        reasons.append(
            f"MIME type mismatch: declared '{provided_mime}' "
            f"but extension suggests '{guessed_mime}'"
        )
        suspicious = True

    # ── Double extension (common obfuscation trick) ───────────────────────────
    name_without_last_ext = filename[: -len(ext)] if ext else filename
    if "." in name_without_last_ext:
        penultimate_ext = os.path.splitext(name_without_last_ext)[1].lower()
        if penultimate_ext in EXECUTABLE_EXTENSIONS | SCRIPT_EXTENSIONS:
            reasons.append(
                f"Double extension detected: '{penultimate_ext}{ext}'"
            )
            suspicious = True

    # ── Very large attachment warning ─────────────────────────────────────────
    if size_bytes is not None and size_bytes > 50 * 1024 * 1024:  # 50 MB
        reasons.append(f"Unusually large attachment: {size_bytes / 1024 / 1024:.1f} MB")

    return {
        "filename": filename,
        "extension": ext,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "suspicious": suspicious,
        "reasons": reasons,
    }
