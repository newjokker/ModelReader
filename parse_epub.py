#!/usr/bin/env python3
"""
Parse an EPUB file into readable text.

Usage:
    python parse_epub.py /path/to/book.epub
    python parse_epub.py /path/to/book.epub --output book.txt
    python parse_epub.py /path/to/book.epub --json --output book.json
    python parse_epub.py /path/to/book.epub --by-chapter chapters/
"""

from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET


CONTAINER_PATH = "META-INF/container.xml"
XHTML_MEDIA_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "application/x-dtbook+xml",
}
SKIP_TAGS = {"script", "style", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "svg", "math"}
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "title",
    "ul",
}
LOGICAL_TITLE_RE = re.compile(
    r"^("
    r"第\s*[0-9零〇一二三四五六七八九十百两]{1,4}\s*[章节回篇部卷].{0,80}"
    r"|[上下中]篇\s+.{1,80}"
    r"|第[一二三四五六七八九十百两]+部分.{0,80}"
    r"|中文版序.{0,80}"
    r"|序\s*言.{0,80}"
    r"|前\s*言.{0,80}"
    r"|引\s*言.{0,80}"
    r"|导\s*读.{0,80}"
    r"|译者后记.{0,80}"
    r"|后\s*记.{0,80}"
    r"|尾\s*声.{0,80}"
    r"|附\s*录.{0,80}"
    r")$"
)


@dataclass
class Chapter:
    index: int
    href: str
    title: str
    text: str
    source_href: str = ""


@dataclass
class EpubDocument:
    path: str
    title: str
    language: str
    creator: str
    chapters: list[Chapter]

    @property
    def text(self) -> str:
        parts = []
        for chapter in self.chapters:
            if chapter.title:
                parts.append(chapter.title)
            if chapter.text:
                parts.append(chapter.text)
        return "\n\n".join(parts).strip()


class ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS or self._skip_stack:
            self._skip_stack.append(tag)
            return
        if tag in BLOCK_TAGS:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_stack:
            self._skip_stack.pop()
            return
        if tag in BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        text = html.unescape(data)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        if text.strip():
            self._parts.append(text)

    def _newline(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


def _xml_namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _ns(root: ET.Element) -> dict[str, str]:
    namespace = _xml_namespace(root.tag)
    return {"n": namespace} if namespace else {}


def _find_text(root: ET.Element, tag: str) -> str:
    for elem in root.iter():
        if elem.tag.endswith("}" + tag) or elem.tag == tag:
            text = "".join(elem.itertext()).strip()
            if text:
                return text
    return ""


def _decode_zip_text(epub: zipfile.ZipFile, name: str) -> str:
    data = epub.read(name)
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_rootfile_path(epub: zipfile.ZipFile) -> str:
    try:
        container_xml = epub.read(CONTAINER_PATH)
    except KeyError as exc:
        raise ValueError(f"Not an EPUB: missing {CONTAINER_PATH}") from exc

    root = ET.fromstring(container_xml)
    ns = _ns(root)
    rootfile = root.find(".//n:rootfile", ns) if ns else root.find(".//rootfile")
    if rootfile is None:
        raise ValueError("Not an EPUB: container.xml has no rootfile")
    full_path = rootfile.attrib.get("full-path", "").strip()
    if not full_path:
        raise ValueError("Not an EPUB: rootfile has no full-path")
    return full_path


def _resolve_href(base_dir: str, href: str) -> str:
    href = urldefrag(href)[0]
    return posixpath.normpath(posixpath.join(base_dir, unquote(href)))


def _manifest_and_spine(opf_root: ET.Element) -> tuple[dict[str, dict[str, str]], list[str]]:
    ns = _ns(opf_root)
    manifest: dict[str, dict[str, str]] = {}
    manifest_items = opf_root.findall(".//n:manifest/n:item", ns) if ns else opf_root.findall(".//manifest/item")
    for item in manifest_items:
        item_id = item.attrib.get("id", "")
        if item_id:
            manifest[item_id] = {
                "href": item.attrib.get("href", ""),
                "media_type": item.attrib.get("media-type", ""),
                "properties": item.attrib.get("properties", ""),
            }

    spine_ids: list[str] = []
    spine_items = opf_root.findall(".//n:spine/n:itemref", ns) if ns else opf_root.findall(".//spine/itemref")
    for itemref in spine_items:
        idref = itemref.attrib.get("idref", "")
        if idref:
            spine_ids.append(idref)
    return manifest, spine_ids


def _html_to_text(source: str) -> str:
    parser = ReadableHTMLParser()
    parser.feed(source)
    parser.close()
    return parser.get_text()


def _first_heading_text(source: str) -> str:
    match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", source, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _html_to_text(match.group(1)).splitlines()[0].strip()


def _remove_leading_title(text: str, title: str) -> str:
    if not title:
        return text
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() == title.strip():
        lines.pop(0)
    return "\n".join(lines).strip()


def _is_toc_like(chapter: Chapter) -> bool:
    title = chapter.title.strip()
    first_lines = [line.strip() for line in chapter.text.splitlines()[:5] if line.strip()]
    return title in {"目录", "目次", "Contents"} or any(line in {"目录", "目次", "Contents"} for line in first_lines)


def _normalize_heading(line: str) -> str:
    line = re.sub(r"\s+", " ", line.replace("\xa0", " ").strip())
    return line.strip(" 　〈〉《》「」『』【】[]◎◆●○")


def _toc_line_to_title(line: str) -> str:
    line = _normalize_heading(line)
    if not line or line in {"目录", "目次", "Contents"}:
        return ""
    patterns = [
        r"^中文版序\s+(.+)$",
        r"^序\s*言\s+(.+)$",
        r"^第\s*[0-9零〇一二三四五六七八九十百两]{1,4}\s*[章节回篇部卷]\s+(.+)$",
        r"^(译者后记|后\s*记|尾\s*声|附\s*录)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            return _normalize_heading(match.group(1))
    return ""


def _is_toc_part_line(line: str) -> bool:
    line = _normalize_heading(line)
    return bool(re.match(r"^第[一二三四五六七八九十百两]+部分\s+.+$", line))


def extract_toc_sections(document: EpubDocument) -> list[dict[str, list[str] | str]]:
    sections: list[dict[str, list[str] | str]] = []
    current: dict[str, list[str] | str] | None = None
    for chapter in document.chapters:
        if not _is_toc_like(chapter):
            continue
        for line in chapter.text.splitlines():
            normalized = _normalize_heading(line)
            title = _toc_line_to_title(normalized)
            if title:
                current = {"title": title, "anchors": [title]}
                sections.append(current)
                continue
            if current is None or not normalized or _is_toc_part_line(normalized):
                continue
            anchors = current["anchors"]
            assert isinstance(anchors, list)
            anchors.append(normalized)
    return sections


def _is_logical_title(line: str) -> bool:
    line = _normalize_heading(line)
    if not line or len(line) > 90:
        return False
    return bool(LOGICAL_TITLE_RE.match(line))


def _next_toc_section_match(line: str, sections: list[dict[str, list[str] | str]], start: int) -> int | None:
    normalized = _normalize_heading(line)
    for offset, section in enumerate(sections[start : start + 3], start):
        anchors = section["anchors"]
        if isinstance(anchors, list) and normalized in anchors:
            return offset
    return None


def _split_chapter_by_headings(
    chapter: Chapter,
    toc_sections: list[dict[str, list[str] | str]],
    section_index: int,
) -> tuple[list[Chapter], int]:
    if _is_toc_like(chapter):
        return [chapter], section_index

    collected_sections: list[tuple[str, list[str]]] = []
    current_title = chapter.title
    current_lines: list[str] = []
    saw_logical_title = False

    for raw_line in chapter.text.splitlines():
        line = raw_line.strip()
        matched_section_index = _next_toc_section_match(line, toc_sections, section_index)
        if matched_section_index is not None or _is_logical_title(line):
            if saw_logical_title:
                collected_sections.append((current_title, current_lines))
                current_lines = []
            elif current_lines and len("\n".join(current_lines).strip()) > 120:
                collected_sections.append((current_title, current_lines))
                current_lines = []
            if matched_section_index is not None:
                section = toc_sections[matched_section_index]
                current_title = str(section["title"])
                section_index = matched_section_index + 1
                if _normalize_heading(line) != current_title:
                    current_lines.append(raw_line)
            else:
                current_title = line
            saw_logical_title = True
            continue
        current_lines.append(raw_line)

    if not saw_logical_title:
        return [chapter], section_index

    collected_sections.append((current_title, current_lines))
    split_chapters = []
    for title, lines in collected_sections:
        text = "\n".join(lines).strip()
        if not text and title == chapter.title:
            continue
        split_chapters.append(
            Chapter(
                index=0,
                href=chapter.href,
                title=title,
                text=text,
                source_href=chapter.source_href or chapter.href,
            )
        )
    return split_chapters or [chapter], section_index


def split_logical_chapters(document: EpubDocument) -> EpubDocument:
    chapters = []
    toc_sections = extract_toc_sections(document)
    toc_section_index = 0
    for chapter in document.chapters:
        split_chapters, toc_section_index = _split_chapter_by_headings(chapter, toc_sections, toc_section_index)
        chapters.extend(split_chapters)
    for index, chapter in enumerate(chapters, 1):
        chapter.index = index
    return EpubDocument(
        path=document.path,
        title=document.title,
        language=document.language,
        creator=document.creator,
        chapters=chapters,
    )


def parse_epub(path: str | Path) -> EpubDocument:
    epub_path = Path(path).expanduser().resolve()
    if not epub_path.exists():
        raise FileNotFoundError(epub_path)

    with zipfile.ZipFile(epub_path) as epub:
        rootfile_path = _read_rootfile_path(epub)
        opf_root = ET.fromstring(epub.read(rootfile_path))
        opf_dir = posixpath.dirname(rootfile_path)
        manifest, spine_ids = _manifest_and_spine(opf_root)

        title = _find_text(opf_root, "title")
        language = _find_text(opf_root, "language")
        creator = _find_text(opf_root, "creator")
        chapters: list[Chapter] = []

        for idref in spine_ids:
            item = manifest.get(idref)
            if not item or item["media_type"] not in XHTML_MEDIA_TYPES:
                continue
            chapter_path = _resolve_href(opf_dir, item["href"])
            try:
                source = _decode_zip_text(epub, chapter_path)
            except KeyError:
                continue
            text = _html_to_text(source)
            if not text:
                continue
            heading = _first_heading_text(source)
            text = _remove_leading_title(text, heading)
            chapters.append(
                Chapter(
                    index=len(chapters) + 1,
                    href=chapter_path,
                    title=heading or f"Chapter {len(chapters) + 1}",
                    text=text,
                    source_href=chapter_path,
                )
            )

    return EpubDocument(
        path=str(epub_path),
        title=title or epub_path.stem,
        language=language,
        creator=creator,
        chapters=chapters,
    )


def format_text(document: EpubDocument, include_metadata: bool = True) -> str:
    parts = []
    if include_metadata:
        parts.append(f"Title: {document.title}")
        if document.creator:
            parts.append(f"Creator: {document.creator}")
        if document.language:
            parts.append(f"Language: {document.language}")
        parts.append(f"Chapters: {len(document.chapters)}")
    for chapter in document.chapters:
        parts.append(f"\n\n# {chapter.index}. {chapter.title}\n\n{chapter.text}")
    return "\n".join(parts).strip() + "\n"


def _text_to_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def document_to_json(document: EpubDocument) -> str:
    data = {
        "path": document.path,
        "title": document.title,
        "language": document.language,
        "creator": document.creator,
        "chapters": [
            {
                "index": chapter.index,
                "href": chapter.href,
                "title": chapter.title,
                "text": _text_to_lines(chapter.text),
                "source_href": chapter.source_href,
            }
            for chapter in document.chapters
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _safe_filename(text: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", text.strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:80]


def write_chapters(document: EpubDocument, output_dir: str | Path) -> None:
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for chapter in document.chapters:
        filename = f"{chapter.index:03d}-{_safe_filename(chapter.title, 'chapter')}.txt"
        path = directory / filename
        path.write_text(f"# {chapter.index}. {chapter.title}\n\n{chapter.text.strip()}\n", encoding="utf-8")
        manifest.append(
            {
                "index": chapter.index,
                "title": chapter.title,
                "href": chapter.href,
                "source_href": chapter.source_href or chapter.href,
                "file": filename,
                "characters": len(chapter.text),
            }
        )
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_output(text: str, output: str | None) -> None:
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse an EPUB file into readable text.")
    parser.add_argument("epub", help="Path to the .epub file")
    parser.add_argument("-o", "--output", help="Write output to this file instead of stdout")
    parser.add_argument("--by-chapter", help="Write one .txt file per chapter into this directory")
    parser.add_argument("--json", action="store_true", help="Output structured JSON instead of plain text")
    parser.add_argument("--no-split-logical", action="store_true", help="Only split by EPUB spine files")
    parser.add_argument("--no-metadata", action="store_true", help="Do not include metadata in plain text output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = parse_epub(args.epub)
        if not args.no_split_logical:
            document = split_logical_chapters(document)
        if args.by_chapter:
            write_chapters(document, args.by_chapter)
        output = document_to_json(document) if args.json else format_text(document, not args.no_metadata)
        if args.output or not args.by_chapter:
            write_output(output, args.output)
    except Exception as exc:
        sys.stderr.write(f"parse_epub: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
