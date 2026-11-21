from datetime import datetime
from functools import cache
from io import BytesIO
from pathlib import Path
import os
from threading import Lock
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from bs4 import BeautifulSoup
from markdownify import markdownify
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

pdf_lock = Lock()


def article_metadata(entry):
    timestamp = entry["published"] or entry["added"]
    return f"{entry['source']} · {datetime.fromtimestamp(timestamp):%Y-%m-%d %H:%M}"


def plain_title(title):
    return " ".join(title.split())


def markdown_export(title, entries):
    sections = [f"# {escape(plain_title(title))}"]
    for entry in entries:
        header = f"## {escape(plain_title(entry['title']))}\n\n{escape(article_metadata(entry))}"
        if entry["link"]:
            header += f"\n\n<{entry['link']}>"
        body = markdownify(entry["body"], heading_style="ATX").strip()
        sections.append(f"{header}\n\n{body or '订阅源未提供正文。'}")
    return ("\n\n---\n\n".join(sections) + "\n").encode("utf-8")


@cache
def pdf_fonts():
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    regular, bold = windows_fonts / "msyh.ttc", windows_fonts / "msyhbd.ttc"
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("ArchiveSans", str(regular)))
        pdfmetrics.registerFont(TTFont("ArchiveSansBold", str(bold)))
        return "ArchiveSans", "ArchiveSansBold"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


def text_blocks(html):
    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img"):
        alt = image.get("alt", "").strip()
        image.replace_with(f"［图片：{alt}］" if alt else "")
    for tag in soup.find_all(["br", "p", "div", "li", "pre", "blockquote", "h1", "h2", "h3", "tr"]):
        tag.insert_after("\n")
    return [" ".join(line.split()) for line in soup.get_text().splitlines() if line.strip()]


def pdf_export(title, entries):
    with pdf_lock:
        return render_pdf(title, entries)


def render_pdf(title, entries):
    output = BytesIO()
    regular, bold = pdf_fonts()
    ink, muted, accent = map(colors.HexColor, ("#182622", "#4e625b", "#176957"))
    body = ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=17, textColor=ink,
                          spaceAfter=7, wordWrap="CJK")
    heading = ParagraphStyle("heading", parent=body, fontName=bold, fontSize=16, leading=24,
                             keepWithNext=True)
    meta = ParagraphStyle("meta", parent=body, fontSize=9, leading=14, textColor=muted)
    cover = ParagraphStyle("cover", parent=heading, fontSize=23, leading=33, textColor=accent)
    story = [Paragraph(escape(plain_title(title)), cover), Spacer(1, 10)]
    for entry in entries:
        story.extend([
            Paragraph(escape(plain_title(entry["title"])), heading),
            Paragraph(escape(article_metadata(entry)), meta),
        ])
        if entry["link"]:
            story.append(Paragraph(f"<link href={quoteattr(entry['link'])}>打开原文</link>", meta))
        for block in text_blocks(entry["body"]) or ["订阅源未提供正文。"]:
            story.append(Paragraph(escape(block), body))
        story.append(Spacer(1, 15))

    def footer(canvas, doc):
        canvas.setFont(regular, 8)
        canvas.setFillColor(muted)
        canvas.setStrokeColor(colors.HexColor("#dbe6e2"))
        canvas.line(48, 39, A4[0] - 48, 39)
        canvas.drawString(48, 25, "我的 RSS / 订阅归档")
        canvas.drawRightString(A4[0] - 48, 25, str(doc.page))

    doc = SimpleDocTemplate(output, pagesize=A4, title=title, leftMargin=48, rightMargin=48,
                            topMargin=47, bottomMargin=55)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def article_export(title, entries, file_format, multiple):
    make_file = pdf_export if file_format == "pdf" else markdown_export
    if not multiple:
        return BytesIO(make_file(title, entries))
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for entry in entries:
            archive.writestr(f"article-{entry['id']:06d}.{file_format}", make_file(title, [entry]))
    output.seek(0)
    return output
