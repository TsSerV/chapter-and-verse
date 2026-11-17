"""Read an Act from legislation.gov.uk as a list of sections."""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import httpx

BASE_URL = "https://www.legislation.gov.uk"
NS = "{http://www.legislation.gov.uk/namespaces/legislation}"
VALID = "{http://purl.org/dc/terms/}valid"


@dataclass(frozen=True)
class Provision:
    act: str  # "ukpga/1996/18"
    number: str  # "94", or "43B" for a section added by a later Act
    title: str
    text: str
    uri: str
    # The date from which this version of the Act's text is in force.
    valid_from: date


async def fetch_act(client: httpx.AsyncClient, act: str) -> bytes:
    # The whole Act as one XML document, at its latest revised version.
    response = await client.get(f"{BASE_URL}/{act}/data.xml", follow_redirects=True)
    response.raise_for_status()
    return response.content


def parse_sections(xml: bytes, act: str) -> list[Provision]:
    root = ET.fromstring(xml)
    body = root.find(f"{NS}Primary/{NS}Body")
    if body is None:
        raise ValueError("No Body element. Is this an Act from legislation.gov.uk?")
    valid_from = date.fromisoformat(root.findtext(f".//{VALID}", default=""))
    sections = []
    # A P1group is one section: its title, then a P1 with the number and the text.
    for group in body.iter(f"{NS}P1group"):
        p1 = group.find(f"{NS}P1")
        if p1 is None:
            continue
        text = "\n".join(lines(p1, []))
        # A repealed section is a row of dots. It has nothing to cite.
        if not re.search("[A-Za-z]", text):
            continue
        sections.append(
            Provision(
                act=act,
                number=inner_text(p1.find(f"{NS}Pnumber")),
                title=inner_text(group.find(f"{NS}Title")),
                text=text,
                uri=p1.get("DocumentURI", ""),
                valid_from=valid_from,
            )
        )
    return sections


def lines(element: ET.Element, numbers: list[str]) -> Iterator[str]:
    # One line per Text element, with the numbers that lead to it in front:
    # "(1) An employee has the right...", "(a) the reason...".
    for child in element:
        tag = child.tag.removeprefix(NS)
        if tag == "Pnumber":
            # The section's own number is the first one, and stays out of the text.
            if element.tag != f"{NS}P1":
                numbers.append(f"({inner_text(child)})")
        elif tag == "Text":
            text = inner_text(child)
            if text:
                yield " ".join([*numbers, text])
                numbers.clear()
        else:
            yield from lines(child, numbers)


def inner_text(element: ET.Element | None) -> str:
    # All the text inside, including text in child elements such as Addition.
    if element is None:
        return ""
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()
