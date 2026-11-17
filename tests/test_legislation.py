from datetime import date

import httpx
import pytest
import respx

from chapter_and_verse.legislation import fetch_act, parse_sections

ACT = "ukpga/1996/18"
URI = "http://www.legislation.gov.uk/ukpga/1996/18/section"
TULRCA = "Trade Union and Labour Relations (Consolidation) Act 1992"

# The shape of legislation.gov.uk's XML, cut down to four sections.
XML = f"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata"
  xmlns:dct="http://purl.org/dc/terms/">
<ukm:Metadata><dct:valid>2026-10-30</dct:valid></ukm:Metadata>
<Primary><Body>
<P1group><Title> The right.</Title>
<P1 DocumentURI="{URI}/94"><Pnumber>94</Pnumber><P1para>
<P2><Pnumber>1</Pnumber><P2para>
<Text>An employee has the right not to be unfairly dismissed by his employer.</Text>
</P2para></P2>
<P2><Pnumber>2</Pnumber><P2para>
<Text>Subsection (1) has effect subject to the provisions of the
  <CommentaryRef Ref="c1"/>{TULRCA}.</Text>
</P2para></P2>
</P1para></P1></P1group>
<P1group><Title><Addition>Meaning of protected disclosure.</Addition></Title>
<P1 DocumentURI="{URI}/43A"><Pnumber><Addition>43A</Addition></Pnumber><P1para>
<Text><Addition>In this Act a protected disclosure means a qualifying disclosure.</Addition></Text>
</P1para></P1></P1group>
<P1group><Title>General.</Title>
<P1 DocumentURI="{URI}/98"><Pnumber>98</Pnumber><P1para>
<P2><Pnumber>1</Pnumber><P2para>
<Text>It is for the employer to show:</Text>
<P3><Pnumber>a</Pnumber><P3para><Text>the reason for the dismissal, and</Text></P3para></P3>
<P3><Pnumber>b</Pnumber><P3para><Text>that it is a reason within subsection (2).</Text></P3para></P3>
</P2para></P2>
<P2><Pnumber>4</Pnumber><P2para>
<P3><Pnumber>a</Pnumber><P3para><Text>depends on whether the employer acted reasonably.</Text></P3para></P3>
</P2para></P2>
</P1para></P1></P1group>
<P1group><Title>. . .</Title>
<P1 DocumentURI="{URI}/99"><Pnumber>99</Pnumber><P1para>
<Text>. . . . . . . . . . . . . . . .</Text>
</P1para></P1></P1group>
</Body></Primary></Legislation>""".encode()


def test_reads_each_section_with_its_number_title_and_address() -> None:
    sections = parse_sections(XML, ACT)

    assert [s.number for s in sections] == ["94", "43A", "98"]
    assert sections[0].title == "The right."
    assert sections[0].uri == f"{URI}/94"
    assert sections[0].act == ACT
    assert sections[0].valid_from == date(2026, 10, 30)


def test_text_is_one_line_per_provision_with_its_numbers() -> None:
    right, _, general = parse_sections(XML, ACT)

    assert right.text.split("\n") == [
        "(1) An employee has the right not to be unfairly dismissed by his employer.",
        f"(2) Subsection (1) has effect subject to the provisions of the {TULRCA}.",
    ]
    assert general.text.split("\n") == [
        "(1) It is for the employer to show:",
        "(a) the reason for the dismissal, and",
        "(b) that it is a reason within subsection (2).",
        "(4) (a) depends on whether the employer acted reasonably.",
    ]


def test_reads_text_that_a_later_act_added() -> None:
    added = parse_sections(XML, ACT)[1]

    assert added.title == "Meaning of protected disclosure."
    assert (
        added.text
        == "In this Act a protected disclosure means a qualifying disclosure."
    )


def test_leaves_out_repealed_sections() -> None:
    assert "99" not in [s.number for s in parse_sections(XML, ACT)]


def test_rejects_a_document_that_is_not_an_act() -> None:
    with pytest.raises(ValueError, match="No Body"):
        parse_sections(b"<html><body>Not found</body></html>", ACT)


@pytest.mark.anyio
@respx.mock
async def test_fetches_the_whole_act_as_xml() -> None:
    route = respx.get("https://www.legislation.gov.uk/ukpga/1996/18/data.xml").mock(
        return_value=httpx.Response(200, content=XML)
    )

    async with httpx.AsyncClient() as client:
        xml = await fetch_act(client, ACT)

    assert route.called
    assert xml == XML
