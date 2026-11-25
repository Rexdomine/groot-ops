"""A research memo as a .docx, built with the standard library (a .docx is a zip of a few XML files)."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{links}</Relationships>"""
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
GREEN = "012D1D"


def _run(text: str, bold: bool = False, italic: bool = False, size: int = 22, color: str = "") -> str:
    props = "".join([
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>', "<w:b/>" if bold else "", "<w:i/>" if italic else "",
        f'<w:color w:val="{color}"/>' if color else "", f'<w:sz w:val="{size}"/>',
    ])
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(*runs: str, space_after: int = 120, indent: int = 0) -> str:
    ind = f'<w:ind w:left="{indent}"/>' if indent else ""
    return f'<w:p><w:pPr><w:spacing w:after="{space_after}"/>{ind}</w:pPr>{"".join(runs)}</w:p>'


class _Links:
    def __init__(self):
        self.items: list[str] = []

    def add(self, url: str, text: str) -> str:
        rid = f"rIdL{len(self.items) + 1}"
        self.items.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                          f'Target="{escape(url, {chr(34): "&quot;"})}" TargetMode="External"/>')
        return f'<w:hyperlink r:id="{rid}">{_run(text, color="1D6F42", size=20)}</w:hyperlink>'


def build_memo(title: str, lawyer: str, firm: str, searches: list[dict], now: datetime | None = None) -> bytes:
    """searches: stored searches with their result dicts; only finished, successful ones are written."""
    now = now or datetime.now()
    links = _Links()
    body = [
        _para(_run("Research memo", bold=True, size=36, color=GREEN), space_after=60),
        _para(_run(title, size=24)),
        _para(_run(f"Prepared for {lawyer}" + (f", {firm}" if firm else "") + f" · {now:%d %B %Y}", size=18, color="6B7570"), space_after=240),
    ]
    for search in searches:
        result = search.get("result") or {}
        body.append(_para(_run("Question: ", bold=True, color=GREEN), _run(search["question"]), space_after=80))
        if result.get("status") != "ok":
            body.append(_para(_run("No authorities found for this question.", italic=True, color="6B7570"), space_after=240))
            continue
        if result.get("answer"):
            body.append(_para(_run(result["answer"])))
        for n, a in enumerate(result.get("authorities") or [], 1):
            body.append(_para(_run(f"{n}. {a['case_name']} ", bold=True), _run(a["citation"]),
                              _run(f" ({a['court']})" if a.get("court") else "", color="6B7570"), space_after=40))
            if a.get("holding"):
                body.append(_para(_run(a["holding"]), indent=360, space_after=40))
            body.append(_para(_run(f"“{a['quote']}”" + (f" ({a['page']})" if a.get("page") else ""), italic=True), indent=360, space_after=40))
            body.append(_para(links.add(a["source_url"], "Open the report on NWLR Online"), indent=360, space_after=160))
        statutes = result.get("statutes") or []
        if statutes:
            body.append(_para(_run("Statutes: ", bold=True), _run("; ".join(f"{s['name']}, {s['provision']}" for s in statutes))))
        if result.get("note"):
            body.append(_para(_run("Note: ", bold=True), _run(result["note"])))
        body.append(_para(_run(""), space_after=120))
    body.append(_para(_run("Prepared with GrootOps Legal from NWLR Online. A research aid: check each authority before relying on it.",
                           italic=True, size=18, color="6B7570")))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS.format(links="".join(links.items)))
        z.writestr("word/document.xml", document)
    return out.getvalue()
