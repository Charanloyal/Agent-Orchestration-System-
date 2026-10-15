"""Isolated PDF text extraction. Reads PDF bytes on stdin, writes JSON on stdout.

Runs in its own process (see app.tools.extract.extract_pdf) so parser bugs, memory blow-ups,
or pathological files cannot affect the worker; the parent enforces a timeout.
"""

import io
import json
import sys


def main() -> int:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()))
        if reader.is_encrypted:
            print(json.dumps({"error": "encrypted_pdf"}))
            return 0
        if len(reader.pages) > max_pages:
            print(json.dumps({"error": "too_many_pages"}))
            return 0
        pages = [page.extract_text() or "" for page in reader.pages]
        title = None
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title)[:500]
    except PdfReadError, ValueError, KeyError, TypeError:
        print(json.dumps({"error": "pdf_unreadable"}))
        return 0
    print(json.dumps({"pages": pages, "title": title}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
