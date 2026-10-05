"""The delivered report, on paper.

The owner asked for the two reports a visitor downloads to be PDFs rather than
markdown files (2026-09-20): a fabrication package is filed, printed and passed
around, and a .md is none of those things. The markdown renderers in
`scheinman.report` stay: they are what the repository's own demo packages and
the tests read, and they are diffable.

Both formats are built from the same structured values (measurements,
violations, anchors, corrections, the proof), so neither is a retelling of the
other. The sentences that are prose rather than data have one owner,
`scheinman.report`, and this module imports them.

This is a print document: white paper, near-black ink, and the blueprint blue
the site uses as the one accent, darkened to hold on white. The drawing follows
the same rules as the one on the evidence page: real geometry at scale, every
dimension a measured number, the old position dashed where the machine moved
something.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from scheinman.correction import CorrectionResult
from scheinman.parts import PartSpec
from scheinman.report import (
    SEVERITY_ORDER,
    not_exercised_sentence,
    proof_sentence,
    rule_scopes,
)
from scheinman.schemas import AnchorKind, Measurement, Rule, UsageContext, Violation

INK = colors.HexColor("#14181f")
MUTED = colors.HexColor("#5a6472")
HAIRLINE = colors.HexColor("#c2cbd8")
PANEL = colors.HexColor("#f2f5f9")
ACCENT = colors.HexColor("#1667a8")
BLOCK = colors.HexColor("#b3261e")
WARN = colors.HexColor("#8a5a00")
PASS = colors.HexColor("#1b6b4a")

SEVERITY_COLOUR = {"BLOCK": BLOCK, "WARN": WARN, "NOTE": ACCENT}

PAGE = A4
MARGIN = 17 * mm
BODY_WIDTH = PAGE[0] - 2 * MARGIN

# What the machine is, said on every delivery so a page that leaves the site
# still carries its own scope. Same limit the evidence page states.
SCOPE_LINE = (
    "Version 1 measures flat plates with round through-holes; any other shape is refused with a "
    "stated reason. Every limit applied here quotes a public engineering record."
)


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.2, leading=13.2, textColor=INK, spaceAfter=0
    )
    return {
        "body": base,
        "lead": ParagraphStyle("lead", parent=base, fontSize=10, leading=14.5),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=INK,
            spaceBefore=0,
            spaceAfter=0,
        ),
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=11, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=8, leading=11),
        "cell": ParagraphStyle("cell", parent=base, fontName="Courier", fontSize=7.2, leading=10),
        "cellright": ParagraphStyle(
            "cellright",
            parent=base,
            fontName="Courier",
            fontSize=7.2,
            leading=10,
            alignment=TA_RIGHT,
        ),
        "monoright": ParagraphStyle(
            "monoright", parent=base, fontName="Courier", fontSize=8, leading=11, alignment=TA_RIGHT
        ),
        "quote": ParagraphStyle(
            "quote",
            parent=base,
            fontName="Helvetica-Oblique",
            fontSize=8.6,
            leading=12.4,
            leftIndent=8,
        ),
        "source": ParagraphStyle(
            "source",
            parent=base,
            fontName="Courier",
            fontSize=7.4,
            leading=10.4,
            textColor=ACCENT,
            leftIndent=8,
        ),
    }


S = _styles()


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rule(colour: colors.Color = HAIRLINE, thickness: float = 0.6) -> Table:
    line = Table([[""]], colWidths=[BODY_WIDTH], rowHeights=[thickness])
    line.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colour)]))
    return line


def _heading(text: str, note: str = "") -> KeepTogether:
    row = Table(
        [[Paragraph(_escape(text), S["h2"]), Paragraph(_escape(note.upper()), S["small"])]],
        colWidths=[BODY_WIDTH * 0.68, BODY_WIDTH * 0.32],
    )
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return KeepTogether([row, _rule(INK, 0.9), Spacer(1, 7)])


@dataclass(frozen=True)
class Head:
    """What the title block says. One line per thing a reader has to trust."""

    part_name: str
    context: UsageContext
    verdict: str
    job_key: str
    submitted_at: str
    rules_evaluated: tuple[str, ...]


def _title_block(head: Head) -> Table:
    cells = [
        ("PART", head.part_name),
        ("DECLARED CONTEXT", f"{head.context.material_series} - {head.context.loading.value}"),
        ("VERDICT", head.verdict),
        ("JOB", head.job_key),
        ("SUBMITTED", head.submitted_at),
        ("RULES EVALUATED", ", ".join(head.rules_evaluated) or "none"),
    ]
    rows = []
    for index in (0, 3):
        rows.append(
            [Paragraph(_escape(label), S["small"]) for label, _ in cells[index : index + 3]]
        )
        rows.append([Paragraph(_escape(value), S["mono"]) for _, value in cells[index : index + 3]])
    width = BODY_WIDTH / 3
    table = Table(rows, colWidths=[width] * 3)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, HAIRLINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, HAIRLINE),
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("SPAN", (0, 0), (0, 0)),
            ]
        )
    )
    return table


class Bar(Flowable):  # type: ignore[misc]
    """Measured against required, drawn to scale.

    The number alone makes a reader do arithmetic to feel the gap. The track
    ends at the required minimum, so a short bar is a part that does not reach
    it and the picture says the same thing the numbers do.
    """

    def __init__(self, measured: float, required: float, unit: str, width: float) -> None:
        super().__init__()
        self.measured = measured
        self.required = required
        self.unit = unit
        self.width = width
        self.height = 26

    def draw(self) -> None:
        c = self.canv
        share = 0 if self.required <= 0 else max(0.0, min(1.0, self.measured / self.required))
        track = self.width
        c.setFont("Courier", 7.4)
        c.setFillColor(MUTED)
        c.drawString(0, 18, f"MEASURED {self.measured:.3f} {self.unit}")
        c.drawRightString(track, 18, f"REQUIRED {self.required:.3f} {self.unit}")
        c.setFillColor(colors.HexColor("#e6eaf0"))
        c.rect(0, 6, track, 6, stroke=0, fill=1)
        c.setFillColor(BLOCK if share < 1 else PASS)
        c.rect(0, 6, track * share, 6, stroke=0, fill=1)
        c.setStrokeColor(INK)
        c.setLineWidth(1)
        c.line(track, 3, track, 15)
        c.setFont("Helvetica", 7.4)
        c.setFillColor(MUTED)
        short = self.required - self.measured
        note = (
            f"The track ends at the required minimum. This part reaches {share * 100:.0f}% of it, "
            f"short by {short:.3f} {self.unit}."
            if share < 1
            else "The track ends at the required minimum. This part clears it."
        )
        c.drawString(0, -4, note)

    def wrap(self, *_: float) -> tuple[float, float]:
        return self.width, self.height


class PlateDrawing(Flowable):  # type: ignore[misc]
    """The plate seen from above, before and after the machine moved a hole.

    One figure, one claim: this hole was here, it is now there, and the edge
    distance that failed is the dimension called out. Nothing decorative is
    drawn; every line is either the part, a dimension or the hole that moved.
    """

    def __init__(self, before: PartSpec, after: PartSpec, width: float) -> None:
        super().__init__()
        self.before = before
        self.after = after
        self.width = width
        self.scale = min((width - 60) / after.length, 200.0 / after.width)
        self.height = after.width * self.scale + 62

    def wrap(self, *_: float) -> tuple[float, float]:
        return self.width, self.height

    def _local(self, spec: PartSpec) -> list[tuple[float, float, float]]:
        """Hole centres measured from the plate's minimum corner.

        `PartSpec` already states them that way (`parts.build_part`: "hole
        coordinates are given from the corner"); the file's own origin is added
        on export and has no business here. Subtracting it once was enough to
        put a hole outside its own plate.
        """
        return [(h.x, h.y, h.diameter) for h in spec.holes]

    def draw(self) -> None:
        c = self.canv
        s = self.scale
        x0, y0 = 26.0, 46.0

        def X(mm_value: float) -> float:
            return x0 + mm_value * s

        def Y(mm_value: float) -> float:
            return y0 + mm_value * s

        length, width = self.after.length, self.after.width
        c.setLineWidth(1.1)
        c.setStrokeColor(ACCENT)
        c.rect(X(0), Y(0), length * s, width * s, stroke=1, fill=0)

        before = self._local(self.before)
        after = self._local(self.after)
        moved = [
            (b, a)
            for b, a in zip(before, after, strict=False)
            if abs(b[0] - a[0]) > 1e-6 or abs(b[1] - a[1]) > 1e-6
        ]

        for bx, by, diameter in (b for b, a in moved):
            c.setStrokeColor(BLOCK)
            c.setLineWidth(0.9)
            c.setDash(3, 3)
            c.circle(X(bx), Y(by), diameter / 2 * s, stroke=1, fill=0)
            c.setDash()

        for ax, ay, diameter in after:
            c.setStrokeColor(ACCENT)
            c.setLineWidth(1.2)
            c.circle(X(ax), Y(ay), diameter / 2 * s, stroke=1, fill=0)
            c.setLineWidth(0.4)
            c.setDash([4, 2, 1, 2], 0)
            c.line(X(ax) - diameter * s * 0.55, Y(ay), X(ax) + diameter * s * 0.55, Y(ay))
            c.line(X(ax), Y(ay) - diameter * s * 0.55, X(ax), Y(ay) + diameter * s * 0.55)
            c.setDash()

        # The move itself, and what it bought, called out into the empty part of
        # the plate with a leader rather than written across the hole it
        # describes. A drawing that overprints its own feature is unreadable.
        if moved:
            (bx, by, _), (ax, ay, diameter) = moved[0]
            radius = diameter / 2 * s
            c.setStrokeColor(PASS)
            c.setLineWidth(1)
            for (mbx, mby, _), (max_, may, _) in moved:
                c.line(X(mbx), Y(mby), X(max_), Y(may))

            # The edge distance the correction had to reach, on the hole the
            # blocking rule fired at.
            c.setLineWidth(0.8)
            c.line(X(0), Y(ay), X(ax) - radius, Y(ay))
            c.line(X(0), Y(ay) - 3, X(0), Y(ay) + 3)
            c.line(X(ax) - radius, Y(ay) - 3, X(ax) - radius, Y(ay) + 3)

            tx, ty = X(length * 0.34), Y(width * 0.58)
            c.setLineWidth(0.6)
            c.line(X(ax) + radius * 0.7, Y(ay) + radius * 0.7, tx - 5, ty - 2)
            c.setFillColor(PASS)
            c.setFont("Courier", 6.8)
            travels = [((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for b, a in moved]
            moves = " and ".join(f"{t:.2f}" for t in travels)
            count = f"{len(moved)} hole moved" if len(moved) == 1 else f"{len(moved)} holes moved"
            c.drawString(tx, ty + 8, f"{count}, by {moves} mm")
            c.drawString(tx, ty - 2, f"e = {ax:.2f} mm ({ax / diameter:.2f} d), corrected")

        c.setStrokeColor(MUTED)
        c.setFillColor(MUTED)
        c.setLineWidth(0.6)
        c.line(X(0), Y(0) - 14, X(length), Y(0) - 14)
        c.line(X(0), Y(0) - 17, X(0), Y(0) - 11)
        c.line(X(length), Y(0) - 17, X(length), Y(0) - 11)
        c.setFont("Courier", 6.8)
        c.drawCentredString(X(length / 2), Y(0) - 25, f"{length:.2f}")
        c.line(X(length) + 12, Y(0), X(length) + 12, Y(width))
        c.line(X(length) + 9, Y(0), X(length) + 15, Y(0))
        c.line(X(length) + 9, Y(width), X(length) + 15, Y(width))
        c.saveState()
        c.translate(X(length) + 20, Y(width / 2))
        c.rotate(90)
        c.drawCentredString(0, 0, f"{width:.2f}")
        c.restoreState()

        c.setFont("Helvetica", 7.4)
        c.setFillColor(MUTED)
        legend = "Top view, to scale. Millimetres. "
        legend += (
            "Dashed red: where each moved hole was submitted. Blue: the corrected part."
            if moved
            else "Blue: the corrected part. No hole moved."
        )
        c.drawString(x0, 6, legend)


def _measurements_table(measurements: list[Measurement], *, with_method: bool = True) -> Table:
    head = ["FEATURE", "QUANTITY", "VALUE", "HOW IT WAS MEASURED"]
    rows = [[Paragraph(_escape(h), S["small"]) for h in head]]
    for m in measurements:
        rows.append(
            [
                Paragraph(_escape(m.feature_id), S["cell"]),
                Paragraph(_escape(m.quantity), S["cell"]),
                Paragraph(f"{m.value:.3f} {_escape(m.unit)}", S["cellright"]),
                Paragraph(_escape(m.method) if with_method else "", S["small"]),
            ]
        )
    widths = [
        BODY_WIDTH * 0.16,
        BODY_WIDTH * 0.30,
        BODY_WIDTH * 0.15,
        BODY_WIDTH * 0.39,
    ]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, HAIRLINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _finding(violation: Violation, scope: str) -> KeepTogether:
    colour = SEVERITY_COLOUR[violation.severity.value].hexval().replace("0x", "#")
    chip = Table(
        [
            [
                Paragraph(
                    f'<font color="{colour}"><b>{_escape(violation.severity.value)}</b></font>',
                    S["mono"],
                ),
                Paragraph(
                    f"rule {_escape(violation.rule_id)} at {_escape(violation.feature_id)}",
                    S["mono"],
                ),
            ]
        ],
        colWidths=[BODY_WIDTH * 0.12, BODY_WIDTH * 0.88],
    )
    chip.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    parts: list[Flowable] = [
        chip,
        Paragraph(_escape(violation.explanation), S["body"]),
        Spacer(1, 8),
        Bar(violation.measured, violation.required_minimum, violation.unit, BODY_WIDTH),
        Spacer(1, 10),
    ]
    if scope:
        parts += [Paragraph(f"<b>Scope.</b> {_escape(scope)}", S["small"]), Spacer(1, 8)]
    parts.append(Paragraph("SOURCES", S["small"]))
    parts.append(Spacer(1, 3))
    for anchor in violation.anchors:
        fixture = (
            " [TEST FIXTURE, not a published engineering fact]"
            if anchor.kind is AnchorKind.TEST_FIXTURE
            else ""
        )
        parts.append(
            Paragraph(f"{_escape(anchor.source)} - {_escape(anchor.locator)}{fixture}", S["source"])
        )
        parts.append(Paragraph(f'"{_escape(anchor.excerpt)}"', S["quote"]))
        parts.append(Spacer(1, 5))
    parts.append(Spacer(1, 6))
    head, tail = parts[:5], parts[5:]
    return KeepTogether([KeepTogether(head), *tail])


class _Numbered(Canvas):  # type: ignore[misc]
    """Page X of Y needs the total, and the total is only known at the end."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, object]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._furniture(total)
            super().showPage()
        super().save()

    def _furniture(self, total: int) -> None:
        kind = getattr(self, "_scheinman_kind", "")
        part = getattr(self, "_scheinman_part", "")
        top = PAGE[1] - MARGIN
        self.setStrokeColor(ACCENT)
        self.setLineWidth(1.6)
        self.line(MARGIN, top + 14, PAGE[0] - MARGIN, top + 14)
        self.setFont("Helvetica-Bold", 10)
        self.setFillColor(INK)
        self.drawString(MARGIN, top + 20, "SCHEINMAN")
        self.setFont("Courier", 7.6)
        self.setFillColor(MUTED)
        self.drawRightString(PAGE[0] - MARGIN, top + 20, kind.upper())
        self.setStrokeColor(HAIRLINE)
        self.setLineWidth(0.5)
        self.line(MARGIN, MARGIN - 12, PAGE[0] - MARGIN, MARGIN - 12)
        self.setFont("Courier", 7)
        self.drawString(MARGIN, MARGIN - 22, part)
        self.drawCentredString(PAGE[0] / 2, MARGIN - 22, f"page {self._pageNumber} of {total}")
        self.drawRightString(PAGE[0] - MARGIN, MARGIN - 22, "PRIVATE - NOT ANNOUNCED - PROTOTYPE")


def _render(story: list[Flowable], head: Head, kind: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 6,
        bottomMargin=MARGIN + 4,
        title=f"{kind}: {head.part_name}",
        author="Scheinman",
        subject=SCOPE_LINE,
    )

    def stamp(canvas: Canvas, _doc: object) -> None:
        canvas._scheinman_kind = kind
        canvas._scheinman_part = f"{head.part_name} - job {head.job_key}"

    doc.build(story, onFirstPage=stamp, onLaterPages=stamp, canvasmaker=_Numbered)
    return buffer.getvalue()


def inspection_pdf(
    *,
    part_name: str,
    context: UsageContext,
    measurements: list[Measurement],
    violations: list[Violation],
    rules_evaluated: list[Rule],
    job_key: str,
    submitted_at: str,
) -> bytes:
    """The measured verdict on the part as it arrived."""
    head = Head(
        part_name=part_name,
        context=context,
        verdict=f"{len(violations)} finding(s)" if violations else "no violations",
        job_key=job_key,
        submitted_at=submitted_at,
        rules_evaluated=tuple(r.rule_id for r in rules_evaluated),
    )
    scopes = rule_scopes(rules_evaluated)
    story: list[Flowable] = [
        Paragraph("Inspection report", S["h2"]),
        Spacer(1, 6),
        _title_block(head),
        Spacer(1, 12),
        Paragraph(
            "A CAD file holds shape, never purpose. The context in the block above was declared "
            "by the requester, and every limit below is applied because of it.",
            S["lead"],
        ),
        Spacer(1, 14),
        _heading("Every measurement", f"{len(measurements)} values"),
        _measurements_table(measurements),
        Spacer(1, 16),
        _heading(
            "What broke" if violations else "What was checked",
            f"{len(violations)} findings" if violations else "no findings",
        ),
    ]
    if not violations:
        passed, silent, inapplicable = not_exercised_sentence(
            context, measurements, rules_evaluated
        )
        story.append(
            Paragraph(
                f"No violations. Rules that passed on measured values: {_escape(passed)}.",
                S["body"],
            )
        )
    else:
        passed, silent, inapplicable = not_exercised_sentence(
            context, measurements, rules_evaluated
        )
        for violation in sorted(
            violations, key=lambda v: (SEVERITY_ORDER[v.severity.value], v.rule_id)
        ):
            story.append(_finding(violation, scopes.get(violation.rule_id, "")))
    tail = []
    if silent:
        tail.append(
            "Not exercised, because no measurement of their quantity exists on this "
            f"part: {silent}."
        )
    if inapplicable:
        tail.append(f"Not applicable to the declared context: {inapplicable}.")
    if tail:
        story += [Spacer(1, 6), Paragraph(_escape(" ".join(tail)), S["small"])]
    story += [Spacer(1, 16), _rule(), Spacer(1, 6), Paragraph(_escape(SCOPE_LINE), S["small"])]
    return _render(story, head, "Inspection report")


def correction_pdf(
    *,
    part_name: str,
    context: UsageContext,
    before: list[Violation],
    result: CorrectionResult,
    rules_evaluated: list[Rule],
    submitted_spec: PartSpec,
    job_key: str,
    submitted_at: str,
) -> bytes:
    """What was wrong, what the machine changed, and the re-measurement that
    proves the corrected file is clean."""
    head = Head(
        part_name=part_name,
        context=context,
        verdict="corrected and proven",
        job_key=job_key,
        submitted_at=submitted_at,
        rules_evaluated=tuple(r.rule_id for r in rules_evaluated),
    )
    scopes = rule_scopes(rules_evaluated)
    head_style = ParagraphStyle("headright", parent=S["small"], alignment=TA_RIGHT)
    rows = [
        [
            Paragraph(_escape(h), S["small"] if i < 3 else head_style)
            for i, h in enumerate(("SEVERITY", "RULE", "FEATURE", "MEASURED", "REQUIRED"))
        ]
    ]
    for violation in sorted(before, key=lambda v: (SEVERITY_ORDER[v.severity.value], v.rule_id)):
        colour = SEVERITY_COLOUR[violation.severity.value].hexval().replace("0x", "#")
        rows.append(
            [
                Paragraph(
                    f'<font color="{colour}"><b>{_escape(violation.severity.value)}</b></font>',
                    S["mono"],
                ),
                Paragraph(_escape(violation.rule_id), S["mono"]),
                Paragraph(_escape(violation.feature_id), S["mono"]),
                Paragraph(f"{violation.measured:g} {_escape(violation.unit)}", S["monoright"]),
                Paragraph(
                    f"{violation.required_minimum:g} {_escape(violation.unit)}", S["monoright"]
                ),
            ]
        )
    found = Table(rows, colWidths=[BODY_WIDTH * w for w in (0.13, 0.14, 0.15, 0.29, 0.29)])
    found.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, HAIRLINE),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story: list[Flowable] = [
        Paragraph("Correction report", S["h2"]),
        Spacer(1, 6),
        _title_block(head),
        Spacer(1, 12),
        Paragraph(
            "Every violation below was fixed by arithmetic on the part's own parameters, and the "
            "corrected file was measured again to prove it. No step of that is a model's opinion.",
            S["lead"],
        ),
        Spacer(1, 14),
        _heading("What broke on the submitted part", f"{len(before)} findings"),
        found,
        Spacer(1, 16),
        _heading("What changed", f"{result.rounds} round(s)"),
        PlateDrawing(submitted_spec, result.spec, BODY_WIDTH),
        Spacer(1, 10),
    ]
    for correction in result.corrections:
        story.append(
            Paragraph(
                f"<b>{_escape(correction.rule_id)}</b> "
                f"({_escape(correction.quantity)}): {_escape(correction.action)}",
                S["body"],
            )
        )
        story.append(Spacer(1, 5))
    for scope in dict.fromkeys(
        scopes.get(v.rule_id, "") for v in before if scopes.get(v.rule_id, "")
    ):
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"<b>Scope.</b> {_escape(scope)}", S["small"]))

    story += [
        Spacer(1, 16),
        _heading("The proof", "re-measured, not re-stated"),
        Paragraph(_escape(proof_sentence(result, rules_evaluated)), S["body"]),
        Spacer(1, 10),
        _measurements_table(list(result.proof), with_method=True),
    ]
    if result.recorded:
        story += [
            Spacer(1, 14),
            _heading("Recorded, not corrected", "guidance and fixtures"),
            Paragraph(
                "A NOTE is guidance, and a test fixture is not an engineering fact. Neither is "
                "ever enforced by moving metal; both are written down here.",
                S["body"],
            ),
            Spacer(1, 6),
        ]
        for violation in sorted(result.recorded, key=lambda v: (v.rule_id, v.feature_id)):
            story.append(
                Paragraph(
                    f"{_escape(violation.severity.value)} {_escape(violation.rule_id)} at "
                    f"{_escape(violation.feature_id)}: measured {violation.measured:g} "
                    f"{_escape(violation.unit)}, guidance minimum "
                    f"{violation.required_minimum:g} {_escape(violation.unit)}",
                    S["mono"],
                )
            )
    story += [Spacer(1, 16), _rule(), Spacer(1, 6), Paragraph(_escape(SCOPE_LINE), S["small"])]
    return _render(story, head, "Correction report")


__all__ = ["PageBreak", "correction_pdf", "inspection_pdf"]
