"""Bounded document extraction in a short-lived process; stdout is private JSON only."""
import io
import json
import logging
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / ".deps")]

from pypdf.errors import LimitReachedError  # noqa: E402


def read_text(path: Path, kind: str, limit: int) -> str:
    data = path.read_bytes()
    if kind == "TXT":
        for encoding in (("utf-16",) if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")):
            try:
                text = data.decode(encoding)
                if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                    raise ValueError("INVALID_FILE")
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("INVALID_FILE")
    elif kind == "DOCX":
        if not data.startswith(b"PK\x03\x04"):
            raise ValueError("INVALID_FILE")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if (len(members) > 2000 or sum(m.file_size for m in members) > 32 * 1024 * 1024
                    or any(m.flag_bits & 1 for m in members)
                    or len({m.filename for m in members}) != len(members)):
                raise ValueError("FILE_COMPLEX")
            if "[Content_Types].xml" not in archive.namelist() or "word/document.xml" not in archive.namelist():
                raise ValueError("INVALID_FILE")
            xml = archive.read("word/document.xml")
            if len(xml) > 8 * 1024 * 1024 or b"<!doctype" in xml.lower() or b"<!entity" in xml.lower():
                raise ValueError("FILE_COMPLEX")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            if root.tag != ns + "document":
                raise ValueError("INVALID_FILE")
            text = "\n".join("".join(n.text or "" for n in p.iter(ns + "t"))
                             for p in root.iter(ns + "p"))
    elif kind == "PDF":
        from pypdf import PdfReader, overwrite_configuration
        overwrite_configuration(
            zlib_maximum_output_length=8 * 1024 * 1024,
            lzw_maximum_output_length=8 * 1024 * 1024,
            run_length_maximum_output_length=8 * 1024 * 1024,
            brotli_maximum_output_length=8 * 1024 * 1024,
            jbig2_maximum_output_length=8 * 1024 * 1024,
            image_maximum_buffer_size=8 * 1024 * 1024,
            stream_decoding_work_maximum_length=32 * 1024 * 1024,
            page_tree_maximum_entries=1000,
            xform_maximum_invocations_per_extraction=500,
        )
        if not data.startswith(b"%PDF-"):
            raise ValueError("INVALID_FILE")
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError("FILE_ENCRYPTED")
        if len(reader.pages) > 100:
            raise ValueError("FILE_COMPLEX")
        parts = []
        for page in reader.pages:
            content = page.get_contents()
            if content is not None and len(content.get_data()) > 8 * 1024 * 1024:
                raise ValueError("FILE_COMPLEX")
            parts.append(page.extract_text() or "")
            if sum(map(len, parts)) > limit:
                raise ValueError("TEXT_TOO_LONG")
        text = "\n".join(parts)
    else:
        raise ValueError("INVALID_FILE")
    if len(text) > limit:
        raise ValueError("TEXT_TOO_LONG")
    if not text.strip():
        raise ValueError("NO_TEXT")
    return text


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        text = read_text(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
        print(json.dumps({"text": text}, ensure_ascii=True))
    except Exception as error:
        known = {"INVALID_FILE", "FILE_COMPLEX", "FILE_ENCRYPTED", "TEXT_TOO_LONG", "NO_TEXT"}
        code = ("FILE_COMPLEX" if isinstance(error, LimitReachedError) else
                str(error) if isinstance(error, ValueError) and str(error) in known else "INVALID_FILE")
        print(json.dumps({"error": code}))
