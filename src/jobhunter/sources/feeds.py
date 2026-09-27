"""Lenient RSS/Atom reading. Job feeds often carry HTML entities XML does not know."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.entities import name2codepoint

_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def _fix_entities(text: str) -> str:
    def named(m: re.Match) -> str:
        name = m.group(1)
        if name in _XML_ENTITIES:
            return m.group(0)
        codepoint = name2codepoint.get(name)
        return f"&#{codepoint};" if codepoint else " "

    text = re.sub(r"&([A-Za-z][A-Za-z0-9]*);", named, text)
    return re.sub(r"&(?!#?\w+;)", "&amp;", text)  # bare ampersands


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed_items(xml_text: str) -> list[dict[str, str]]:
    """Each <item>/<entry> as {child tag: text}. The first child of a name wins."""
    root = ET.fromstring(_fix_entities(xml_text))
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        for child in node:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "link" and not text:
                text = child.attrib.get("href", "")
            fields.setdefault(name, text)
        items.append(fields)
    return items
