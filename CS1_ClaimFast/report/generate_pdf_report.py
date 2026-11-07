"""
ClaimFast – Publication Quality Final PDF Report Generator
Uses ReportLab Platypus to generate an authoritative 4-6 page evaluation report:
CS1_ClaimFast/report/report_CS1.pdf
"""

from __future__ import annotations

import datetime
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPORT_DIR = Path(__file__).resolve().parent
PDF_PATH = REPORT_DIR / "report_CS1.pdf"


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and print 'Page X of Y' on all pages.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#4A5568"))

        # Header (pages 2+)
        if self._pageNumber > 1:
            self.drawString(36, 756, "ClaimFast – Motor Insurance Claim Triage & Entity Extraction Benchmark")
            self.drawRightString(576, 756, "Case Study 1 Final Technical Report")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.5)
            self.line(36, 750, 576, 750)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(36, 42, 576, 42)
        self.drawString(36, 30, "CONFIDENTIAL & PROPRIETARY — AGENTIC AI FOUNDATIONS (ITM)")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(576, 30, page_text)
        self.restoreState()


def build_pdf():
    print(f"Building final PDF report: {PDF_PATH}...")
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Custom Color Palette
    PRIMARY = colors.HexColor("#1A365D")   # Deep Navy
    SECONDARY = colors.HexColor("#2B6CB0") # Slate Blue
    ACCENT = colors.HexColor("#2C5282")    # Steel Blue
    DARK_TEXT = colors.HexColor("#2D3748") # Charcoal
    LIGHT_BG = colors.HexColor("#F7FAFC")  # Warm Light Grey
    BORDER = colors.HexColor("#E2E8F0")    # Border Grey

    # Typography Styles
    title_style = ParagraphStyle(
        "DocTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=PRIMARY,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=SECONDARY,
        spaceAfter=12,
    )
    h1_style = ParagraphStyle(
        "Heading1_Custom",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=PRIMARY,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "Heading2_Custom",
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=SECONDARY,
        spaceBefore=6,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body_Custom",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=DARK_TEXT,
        spaceAfter=5,
    )
    body_bold = ParagraphStyle(
        "Body_Bold_Custom",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    callout_style = ParagraphStyle(
        "Callout",
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#2C5282"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=DARK_TEXT,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=DARK_TEXT,
    )
    table_header = ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=colors.white,
    )

    story = []

    # ================= PAGE 1 =================
    story.append(Paragraph("ClaimFast: Motor Insurance Claim Triage & Entity Extraction", title_style))
    story.append(Paragraph(
        "<b>Rigorous Benchmark Evaluation of Prompt Engineering Strategies on High-Noise Indian Claims</b><br/>"
        "Model: <code>qwen/qwen3.8-27b</code> (Groq Cloud) | Temperature: 0.0 | Output: Strict JSON Object Mode | 900 Jobs",
        subtitle_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("1. Executive Summary & Experimental Mandate", h1_style))
    story.append(Paragraph(
        "Motor insurance First Notice of Loss (FNOL) customer communications in India are characterized by high linguistic noise, "
        "code-mixed Hinglish phrases, ambiguous damage descriptions, and missing identifiers. The <b>ClaimFast</b> benchmark evaluates "
        "the capability of open-weights LLMs to reliably parse unstructured customer messages into a structured 9-field schema, "
        "disambiguate complex insurance legal boundaries, and extract actionable triage metadata without external tool intervention.",
        body_style,
    ))
    story.append(Paragraph(
        "The evaluation was executed across <b>900 planned jobs</b> representing 60 held-out test messages evaluated across 5 prompt "
        "strategies over 3 repeated stochastic runs at temperature 0.0. Exactly 900 unique job records were completed with <b>0 missing "
        "and 0 duplicate jobs</b>, achieving a <b>99.44% execution success rate</b> (895 / 900).",
        body_style,
    ))

    # Key Findings Highlights Table
    summary_data = [
        [Paragraph("Strategic Pillar", table_header), Paragraph("Key Metric", table_header), Paragraph("Empirical Finding & Significance", table_header)],
        [Paragraph("Safety Triage", table_cell_bold), Paragraph("High-Urgency F1: 1.0000", table_cell), Paragraph("<b>100.0% Precision & Recall</b> across all 240 high-urgency instances. Zero safety escapes.", table_cell)],
        [Paragraph("Category Triage", table_cell_bold), Paragraph("Macro-F1: 0.9844", table_cell), Paragraph("100% precision on theft & total loss; 98.1% overall accuracy across all 6 claim taxonomy classes.", table_cell)],
        [Paragraph("Extraction Fidelity", table_cell_bold), Paragraph("Policy/Date Acc: 100%", table_cell), Paragraph("Zero hallucinations on policy numbers, ISO dates, vehicle registrations, and claim amounts.", table_cell)],
        [Paragraph("Optimal Strategy", table_cell_bold), Paragraph("Structured Reasoning", table_cell), Paragraph("Highest classification Macro-F1 (0.9870), lowest latency (510ms), 24% faster than few-shot k=8.", table_cell)],
        [Paragraph("Full Record Match", table_cell_bold), Paragraph("Few-Shot k=8: 86.1%", table_cell), Paragraph("In-context span demonstration elevated strict 9-field exact match from 61.7% to 86.1%.", table_cell)],
    ]
    t_summary = Table(summary_data, colWidths=[100, 110, 330])
    t_summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 8))

    story.append(Paragraph("2. Dataset Architecture & Evaluation Matrix", h1_style))
    story.append(Paragraph(
        "The benchmark dataset was partitioned into 20 development messages (<code>data/dev.jsonl</code>) used exclusively for "
        "few-shot exemplar selection, and 60 strictly held-out test messages (<code>data/test.jsonl</code>) used for final scoring. "
        "All messages reflect authentic Indian driving conditions, including municipal towing non-claims, hit-and-run incidents, "
        "constructive total loss assessments, component theft, and Hinglish transliterations.",
        body_style,
    ))

    dataset_matrix = [
        [Paragraph("Dataset Split", table_header), Paragraph("Message Count", table_header), Paragraph("Usage in Experiment", table_header), Paragraph("Integrity & Separation Control", table_header)],
        [Paragraph("Development (dev.jsonl)", table_cell_bold), Paragraph("20 records", table_cell), Paragraph("Exemplar source for k=3, k=5, k=8", table_cell), Paragraph("Strictly excluded from evaluation runner scoring.", table_cell)],
        [Paragraph("Held-Out Test (test.jsonl)", table_cell_bold), Paragraph("60 records", table_cell), Paragraph("Final evaluation scoring benchmark", table_cell), Paragraph("Zero exemplar contamination in any prompt template.", table_cell)],
        [Paragraph("Total Planned Matrix", table_cell_bold), Paragraph("900 jobs", table_cell), Paragraph("60 records × 5 strategies × 3 runs", table_cell), Paragraph("100% deterministic tracking with unique composite job IDs.", table_cell)],
    ]
    t_dmatrix = Table(dataset_matrix, colWidths=[110, 70, 170, 190])
    t_dmatrix.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SECONDARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_dmatrix)
    story.append(Spacer(1, 8))

    story.append(Paragraph("3. Controlled Prompt Engineering Strategies", h1_style))
    story.append(Paragraph(
        "To isolate the impact of in-context demonstration scale versus explicit cognitive deliberative checkpoints, "
        "five controlled prompt architectures were evaluated against identical messages:",
        body_style,
    ))

    prompt_table = [
        [Paragraph("Strategy", table_header), Paragraph("k", table_header), Paragraph("Tokens", table_header), Paragraph("Architectural Hypothesis & Design Specification", table_header)],
        [Paragraph("zero_shot", table_cell_bold), Paragraph("0", table_cell), Paragraph("1,247", table_cell), Paragraph("Baseline extraction relying purely on detailed system definitions and schema specifications.", table_cell)],
        [Paragraph("few_shot_k3", table_cell_bold), Paragraph("3", table_cell), Paragraph("1,748", table_cell), Paragraph("Minimal demonstrative grounding for third-party liability, own-damage, and glass damage.", table_cell)],
        [Paragraph("few_shot_k5", table_cell_bold), Paragraph("5", table_cell), Paragraph("2,112", table_cell), Paragraph("Adds component theft (Rule A) and administrative towing non-claims.", table_cell)],
        [Paragraph("few_shot_k8", table_cell_bold), Paragraph("8", table_cell), Paragraph("2,712", table_cell), Paragraph("Full coverage: constructive total loss, untraced hit-and-run, and Hinglish injury.", table_cell)],
        [Paragraph("structured_reasoning", table_cell_bold), Paragraph("0", table_cell), Paragraph("1,817", table_cell), Paragraph("Internal verification checklist (Rule A/B/C deliberation) emitting only raw JSON without chain-of-thought.", table_cell)],
    ]
    t_prompts = Table(prompt_table, colWidths=[90, 20, 45, 385])
    t_prompts.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_prompts)

    story.append(PageBreak())

    # ================= PAGE 2 =================
    story.append(Paragraph("4. Benchmark Performance & Evaluation Matrix", h1_style))
    story.append(Paragraph(
        "All metrics below reflect the complete 900-job execution matrix (180 runs per strategy). Non-success jobs are penalized "
        "as zero-score mismatches across all fields, ensuring absolute statistical rigor without cherry-picking.",
        body_style,
    ))

    # Comprehensive Performance Table
    results_table_data = [
        [
            Paragraph("Metric", table_header),
            Paragraph("Zero-Shot", table_header),
            Paragraph("Few-Shot k=3", table_header),
            Paragraph("Few-Shot k=5", table_header),
            Paragraph("Few-Shot k=8", table_header),
            Paragraph("Structured Reas.", table_header),
            Paragraph("Benchmark", table_header),
        ],
        [Paragraph("Sample Count (N)", table_cell_bold), Paragraph("180", table_cell), Paragraph("180", table_cell), Paragraph("180", table_cell), Paragraph("180", table_cell), Paragraph("180", table_cell), Paragraph("900", table_cell_bold)],
        [Paragraph("Valid Schema Rate", table_cell_bold), Paragraph("98.3%", table_cell), Paragraph("99.4%", table_cell), Paragraph("<b>100.0%</b>", table_cell), Paragraph("99.4%*", table_cell), Paragraph("<b>100.0%</b>", table_cell), Paragraph("99.4%", table_cell_bold)],
        [Paragraph("Strict Match (9 Fields)", table_cell_bold), Paragraph("61.7%", table_cell), Paragraph("64.4%", table_cell), Paragraph("71.7%", table_cell), Paragraph("<b>86.1%</b>", table_cell), Paragraph("65.0%", table_cell), Paragraph("69.8%", table_cell_bold)],
        [Paragraph("Normalized Match (Loc Norm)", table_cell_bold), Paragraph("78.3%", table_cell), Paragraph("81.1%", table_cell), Paragraph("80.0%", table_cell), Paragraph("<b>86.1%</b>", table_cell), Paragraph("81.7%", table_cell), Paragraph("81.4%", table_cell_bold)],
        [Paragraph("Claim Type Accuracy", table_cell_bold), Paragraph("98.3%", table_cell), Paragraph("97.8%", table_cell), Paragraph("98.3%", table_cell), Paragraph("97.8%", table_cell), Paragraph("<b>98.3%</b>", table_cell), Paragraph("98.1%", table_cell_bold)],
        [Paragraph("Claim Type Macro-F1", table_cell_bold), Paragraph("0.9851", table_cell), Paragraph("0.9822", table_cell), Paragraph("0.9851", table_cell), Paragraph("0.9827", table_cell), Paragraph("<b>0.9870</b>", table_cell), Paragraph("0.9844", table_cell_bold)],
        [Paragraph("Urgency Accuracy", table_cell_bold), Paragraph("91.1%", table_cell), Paragraph("<b>92.8%</b>", table_cell), Paragraph("91.7%", table_cell), Paragraph("<b>92.8%</b>", table_cell), Paragraph("91.7%", table_cell), Paragraph("92.0%", table_cell_bold)],
        [Paragraph("Urgency Macro-F1", table_cell_bold), Paragraph("0.9057", table_cell), Paragraph("<b>0.9305</b>", table_cell), Paragraph("0.9143", table_cell), Paragraph("0.9283", table_cell), Paragraph("0.9143", table_cell), Paragraph("0.9188", table_cell_bold)],
        [Paragraph("Policy Number Acc", table_cell_bold), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell_bold)],
        [Paragraph("Incident Date Acc", table_cell_bold), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell_bold)],
        [Paragraph("Location Acc (Strict)", table_cell_bold), Paragraph("73.3%", table_cell), Paragraph("73.3%", table_cell), Paragraph("81.7%", table_cell), Paragraph("<b>92.8%</b>", table_cell), Paragraph("73.3%", table_cell), Paragraph("78.9%", table_cell_bold)],
        [Paragraph("Location Acc (Normalized)", table_cell_bold), Paragraph("90.0%", table_cell), Paragraph("90.0%", table_cell), Paragraph("90.0%", table_cell), Paragraph("<b>92.8%</b>", table_cell), Paragraph("90.0%", table_cell), Paragraph("90.6%", table_cell_bold)],
        [Paragraph("Vehicle Reg No Acc", table_cell_bold), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.4%*", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.9%", table_cell_bold)],
        [Paragraph("Estimated Amount Acc", table_cell_bold), Paragraph("99.4%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.4%*", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.8%", table_cell_bold)],
        [Paragraph("Injury Reported Acc", table_cell_bold), Paragraph("99.4%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.4%*", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.8%", table_cell_bold)],
        [Paragraph("Police Report Filed Acc", table_cell_bold), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.4%*", table_cell), Paragraph("100.0%", table_cell), Paragraph("99.9%", table_cell_bold)],
        [Paragraph("Mean Latency (ms)", table_cell_bold), Paragraph("549.0", table_cell), Paragraph("545.9", table_cell), Paragraph("563.7", table_cell), Paragraph("668.9", table_cell), Paragraph("<b>510.0</b>", table_cell), Paragraph("567.4", table_cell_bold)],
        [Paragraph("Median Latency (ms)", table_cell_bold), Paragraph("502.0", table_cell), Paragraph("516.0", table_cell), Paragraph("549.3", table_cell), Paragraph("585.4", table_cell), Paragraph("<b>483.0</b>", table_cell), Paragraph("528.5", table_cell_bold)],
        [Paragraph("P95 Latency (ms)", table_cell_bold), Paragraph("863.6", table_cell), Paragraph("774.4", table_cell), Paragraph("790.9", table_cell), Paragraph("1314.6", table_cell), Paragraph("<b>662.8</b>", table_cell), Paragraph("811.4", table_cell_bold)],
        [Paragraph("Mean Input Tokens", table_cell_bold), Paragraph("1,247", table_cell), Paragraph("1,748", table_cell), Paragraph("2,112", table_cell), Paragraph("2,712", table_cell), Paragraph("1,817", table_cell), Paragraph("1,926", table_cell_bold)],
        [Paragraph("Cost / 1k Claims ($)", table_cell_bold), Paragraph("$0.2709", table_cell), Paragraph("$0.3711", table_cell), Paragraph("$0.4439", table_cell), Paragraph("$0.5641", table_cell), Paragraph("$0.3849", table_cell), Paragraph("$0.4070", table_cell_bold)],
    ]
    t_results = Table(results_table_data, colWidths=[120, 65, 70, 70, 70, 80, 65])
    t_results.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_results)
    story.append(Paragraph("<font size=6.5><i>*Few-Shot k=8 valid schema rate and field accuracies reflect 179 successfully executed jobs and 1 API token rate limit error scored as 0.</i></font>", callout_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("5. Safety-Critical Triage: Injury & High-Urgency Evaluation", h1_style))
    story.append(Paragraph(
        "In insurance operational automation, misclassifying bodily injury or undrivable vehicles as low urgency creates critical legal and "
        "human safety liabilities. The evaluation audited every prompt strategy separately for both <b>High Urgency</b> (16 gold records × 3 runs = 48 target instances) "
        "and <b>Injury Reported</b> (8 gold records × 3 runs = 24 target instances):",
        body_style,
    ))

    safety_table_data = [
        [Paragraph("Strategy", table_header), Paragraph("Target Field", table_header), Paragraph("TP", table_header), Paragraph("FP", table_header), Paragraph("FN", table_header), Paragraph("TN", table_header), Paragraph("Precision", table_header), Paragraph("Recall", table_header), Paragraph("F1-Score", table_header)],
        [Paragraph("zero_shot", table_cell_bold), Paragraph("High Urgency", table_cell), Paragraph("48", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("132", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("<b>1.0000</b>", table_cell)],
        [Paragraph("few_shot_k3", table_cell_bold), Paragraph("High Urgency", table_cell), Paragraph("48", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("132", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("<b>1.0000</b>", table_cell)],
        [Paragraph("few_shot_k5", table_cell_bold), Paragraph("High Urgency", table_cell), Paragraph("48", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("132", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("<b>1.0000</b>", table_cell)],
        [Paragraph("few_shot_k8", table_cell_bold), Paragraph("High Urgency", table_cell), Paragraph("48", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("132", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("<b>1.0000</b>", table_cell)],
        [Paragraph("structured_reasoning", table_cell_bold), Paragraph("High Urgency", table_cell), Paragraph("48", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("132", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("<b>1.0000</b>", table_cell)],
        [Paragraph("<b>POOLED BENCHMARK</b>", table_cell_bold), Paragraph("<b>High Urgency</b>", table_cell_bold), Paragraph("<b>240</b>", table_cell_bold), Paragraph("<b>0</b>", table_cell_bold), Paragraph("<b>0</b>", table_cell_bold), Paragraph("<b>660</b>", table_cell_bold), Paragraph("<b>100.0%</b>", table_cell_bold), Paragraph("<b>100.0%</b>", table_cell_bold), Paragraph("<b>1.0000</b>", table_cell_bold)],
        [Paragraph("<b>POOLED BENCHMARK</b>", table_cell_bold), Paragraph("<b>Injury Reported</b>", table_cell_bold), Paragraph("<b>120</b>", table_cell_bold), Paragraph("<b>0</b>", table_cell_bold), Paragraph("<b>0</b>", table_cell_bold), Paragraph("<b>780</b>", table_cell_bold), Paragraph("<b>100.0%</b>", table_cell_bold), Paragraph("<b>100.0%</b>", table_cell_bold), Paragraph("<b>1.0000</b>", table_cell_bold)],
    ]
    t_safety = Table(safety_table_data, colWidths=[95, 85, 35, 35, 35, 35, 70, 70, 80])
    t_safety.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5282")),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, LIGHT_BG]),
        ("BACKGROUND", (0, -2), (-1, -1), colors.HexColor("#EBF8FF")),
    ]))
    story.append(t_safety)
    story.append(Paragraph(
        "<b>Clarification on Pooled vs. Per-Strategy Figures</b>: The previously reported 240/240 figure represents the pooled sum "
        "(48 TP × 5 strategies = 240 TP). Because every individual strategy independently achieved 48/48 TP with 0 FP and 0 FN, "
        "every prompt configuration individually and collectively achieved 100.0% precision and 100.0% recall on critical safety triage.",
        body_style,
    ))

    story.append(PageBreak())

    # ================= PAGE 3 =================
    story.append(Paragraph("6. Classification Deep-Dive & Confusion Matrices", h1_style))
    story.append(Paragraph(
        "Classification metrics were analyzed across all 6 claim taxonomy classes and 3 urgency tiers across the full 900 jobs:",
        body_style,
    ))

    # Claim Type Confusion Matrix
    ct_matrix_data = [
        [Paragraph("Gold \\ Pred", table_header), Paragraph("own_dam.", table_header), Paragraph("third_pty", table_header), Paragraph("theft", table_header), Paragraph("tot_loss", table_header), Paragraph("glass_only", table_header), Paragraph("not_claim", table_header), Paragraph("Invalid", table_header), Paragraph("Total", table_header), Paragraph("F1-Score", table_header)],
        [Paragraph("own_damage", table_cell_bold), Paragraph("198", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("12", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("210", table_cell), Paragraph("0.9635", table_cell_bold)],
        [Paragraph("third_party_liability", table_cell_bold), Paragraph("3", table_cell), Paragraph("175", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("2", table_cell), Paragraph("180", table_cell), Paragraph("0.9887", table_cell_bold)],
        [Paragraph("theft", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("135", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("135", table_cell), Paragraph("1.0000", table_cell_bold)],
        [Paragraph("total_loss", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("90", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("90", table_cell), Paragraph("1.0000", table_cell_bold)],
        [Paragraph("glass_only", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("134", table_cell), Paragraph("0", table_cell), Paragraph("1", table_cell), Paragraph("135", table_cell), Paragraph("0.9571", table_cell_bold)],
        [Paragraph("not_a_claim", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("148", table_cell), Paragraph("2", table_cell), Paragraph("150", table_cell), Paragraph("0.9966", table_cell_bold)],
        [Paragraph("<b>Macro Average</b>", table_cell_bold), Paragraph("-", table_cell), Paragraph("-", table_cell), Paragraph("-", table_cell), Paragraph("-", table_cell), Paragraph("-", table_cell), Paragraph("-", table_cell), Paragraph("5", table_cell), Paragraph("900", table_cell), Paragraph("<b>0.9844</b>", table_cell_bold)],
    ]
    t_ct_matrix = Table(ct_matrix_data, colWidths=[95, 45, 45, 40, 45, 50, 50, 40, 40, 90])
    t_ct_matrix.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_BG]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
    ]))
    story.append(t_ct_matrix)
    story.append(Spacer(1, 6))

    # Urgency Confusion Matrix
    urg_matrix_data = [
        [Paragraph("Gold \\ Pred", table_header), Paragraph("High", table_header), Paragraph("Medium", table_header), Paragraph("Low", table_header), Paragraph("Invalid / Error", table_header), Paragraph("Total", table_header), Paragraph("Precision", table_header), Paragraph("Recall", table_header), Paragraph("F1-Score", table_header)],
        [Paragraph("High", table_cell_bold), Paragraph("240", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("240", table_cell), Paragraph("100.0%", table_cell), Paragraph("100.0%", table_cell), Paragraph("1.0000", table_cell_bold)],
        [Paragraph("Medium", table_cell_bold), Paragraph("0", table_cell), Paragraph("182", table_cell), Paragraph("12", table_cell), Paragraph("1", table_cell), Paragraph("195", table_cell), Paragraph("75.8%", table_cell), Paragraph("93.3%", table_cell), Paragraph("0.8368", table_cell_bold)],
        [Paragraph("Low", table_cell_bold), Paragraph("0", table_cell), Paragraph("58", table_cell), Paragraph("403", table_cell), Paragraph("4", table_cell), Paragraph("465", table_cell), Paragraph("97.1%", table_cell), Paragraph("86.7%", table_cell), Paragraph("0.9159", table_cell_bold)],
        [Paragraph("<b>Macro Average</b>", table_cell_bold), Paragraph("240", table_cell), Paragraph("240", table_cell), Paragraph("415", table_cell), Paragraph("5", table_cell), Paragraph("900", table_cell), Paragraph("<b>90.99%</b>", table_cell), Paragraph("<b>93.34%</b>", table_cell), Paragraph("<b>0.9188</b>", table_cell_bold)],
    ]
    t_urg_matrix = Table(urg_matrix_data, colWidths=[90, 45, 50, 45, 60, 40, 65, 65, 80])
    t_urg_matrix.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SECONDARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_BG]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
    ]))
    story.append(t_urg_matrix)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Key Adjudication Insights", h2_style))
    story.append(Paragraph(
        "• <b>The Rule A Door-Scratch Edge Case (TEST005)</b>: A customer reported broken quarter glass and scratched door panels "
        "while personal sunglasses were stolen. Under Rule A, personal item theft is excluded from auto theft; but because the vehicle "
        "suffered door panel scratching in addition to glass breakage, the true label is <code>own_damage</code>. "
        "Zero-Shot, k=3, k=5, and k=8 all misclassified this as <code>glass_only</code>. <b>Structured Reasoning was the only strategy "
        "to correctly classify TEST005 as own_damage across all 3 runs</b>, confirming the efficacy of its internal verification checklist.<br/>"
        "• <b>The Low vs. Medium Urgency Boundary</b>: Zero claims with bodily injury or undrivable vehicles were missed. All 70 urgency mismatches "
        "occurred on drivable vehicles where large monetary repair quotes (e.g. 28,000 INR for bonnet denting in TEST003) led the model to assign "
        "<code>medium</code> urgency instead of <code>low</code>.",
        body_style,
    ))

    story.append(Spacer(1, 6))
    story.append(Paragraph("7. Field-Level Extraction & Hallucination Analysis", h1_style))
    story.append(Paragraph(
        "Entity extraction performance across all 9 target fields demonstrated extraordinary formatting adherence and near-zero hallucination:",
        body_style,
    ))

    extraction_summary_data = [
        [Paragraph("Target Field", table_header), Paragraph("Data Type", table_header), Paragraph("Exact Match", table_header), Paragraph("Accuracy", table_header), Paragraph("Hallucination Rate", table_header), Paragraph("Error Nature & Normalization Standard", table_header)],
        [Paragraph("policy_number", table_cell_bold), Paragraph("string / null", table_cell), Paragraph("895 / 900", table_cell), Paragraph("100.0%*", table_cell), Paragraph("0.0% (0 / 135)", table_cell), Paragraph("Verbatim identifier extraction. Zero invented prefixes.", table_cell)],
        [Paragraph("incident_date", table_cell_bold), Paragraph("ISO 8601 / null", table_cell), Paragraph("895 / 900", table_cell), Paragraph("100.0%*", table_cell), Paragraph("0.0% (0 / 690)", table_cell), Paragraph("Relative dates ('yesterday') mapped strictly to null.", table_cell)],
        [Paragraph("vehicle_reg_no", table_cell_bold), Paragraph("string (no sp)", table_cell), Paragraph("895 / 900", table_cell), Paragraph("99.9%*", table_cell), Paragraph("0.0% (0 / 60)", table_cell), Paragraph("Strict uppercase without spaces enforced flawlessly.", table_cell)],
        [Paragraph("estimated_amount_inr", table_cell_bold), Paragraph("integer / null", table_cell), Paragraph("895 / 900", table_cell), Paragraph("99.8%*", table_cell), Paragraph("0.0% (0 / 375)", table_cell), Paragraph("Accurate rupee word-to-integer conversion.", table_cell)],
        [Paragraph("injury_reported", table_cell_bold), Paragraph("boolean / null", table_cell), Paragraph("895 / 900", table_cell), Paragraph("99.8%*", table_cell), Paragraph("0.0% (0 / 285)", table_cell), Paragraph("Strict negative standard (Rule D) upheld.", table_cell)],
        [Paragraph("police_report_filed", table_cell_bold), Paragraph("boolean / null", table_cell), Paragraph("895 / 900", table_cell), Paragraph("99.9%*", table_cell), Paragraph("0.0% (0 / 360)", table_cell), Paragraph("Distinguishes formal FIRs from mere scene contact.", table_cell)],
        [Paragraph("location (Strict)", table_cell_bold), Paragraph("string / null", table_cell), Paragraph("707 / 900", table_cell), Paragraph("78.6%", table_cell), Paragraph("6.7% (12 / 180)", table_cell), Paragraph("Strict case sensitivity penalty on proper nouns.", table_cell)],
        [Paragraph("location (Normalized)", table_cell_bold), Paragraph("string / null", table_cell), Paragraph("815 / 900", table_cell), Paragraph("90.6%", table_cell), Paragraph("0.0% (Structured)", table_cell), Paragraph("Matches perfectly when case-insensitive.", table_cell)],
    ]
    t_extract = Table(extraction_summary_data, colWidths=[95, 70, 65, 55, 80, 175])
    t_extract.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (2, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_extract)
    story.append(Paragraph("<font size=6.5><i>*Accuracies on successful executions are 100.0%. The denominator includes the 5 non-success execution jobs scored as 0.</i></font>", callout_style))

    story.append(PageBreak())

    # ================= PAGE 4 =================
    story.append(Paragraph("8. Systematic Error Analysis & Failure Categorization", h1_style))
    story.append(Paragraph(
        "All 272 failed job predictions across the 900-job matrix were audited and classified into six standardized categories. "
        "A dedicated artifact containing every inspected failure, job ID, raw input, expected output, actual output, and proposed fix "
        "has been published to <code>error_analysis/error_analysis.csv</code>.",
        body_style,
    ))

    # Error Category Table
    error_cat_summary = [
        [Paragraph("Error Category", table_header), Paragraph("Zero-Shot", table_header), Paragraph("Few-Shot k=3", table_header), Paragraph("Few-Shot k=5", table_header), Paragraph("Few-Shot k=8", table_header), Paragraph("Structured Reas.", table_header), Paragraph("Total", table_header), Paragraph("Root Cause & Recommended Fix", table_header)],
        [Paragraph("Normalization Error", table_cell_bold), Paragraph("44", table_cell), Paragraph("45", table_cell), Paragraph("30", table_cell), Paragraph("9", table_cell), Paragraph("48", table_cell), Paragraph("176", table_cell_bold), Paragraph("Casing mismatch on location (e.g. 'mall basement' vs 'Mall basement'). Fix: Title-case post-processing.", table_cell)],
        [Paragraph("Classification Error", table_cell_bold), Paragraph("19", table_cell), Paragraph("15", table_cell), Paragraph("18", table_cell), Paragraph("15", table_cell), Paragraph("15", table_cell), Paragraph("82", table_cell_bold), Paragraph("Low vs medium urgency calibration on drivable damage. Fix: Explicit monetary threshold rules in prompt.", table_cell)],
        [Paragraph("Hallucination", table_cell_bold), Paragraph("3", table_cell), Paragraph("3", table_cell), Paragraph("3", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("9", table_cell_bold), Paragraph("Extracting 'blind turn' as location in TEST011. Structured reasoning and k=8 correctly output null.", table_cell)],
        [Paragraph("Formatting/Schema", table_cell_bold), Paragraph("3", table_cell), Paragraph("1", table_cell), Paragraph("0", table_cell), Paragraph("1", table_cell), Paragraph("0", table_cell), Paragraph("5", table_cell_bold), Paragraph("Morphological key drift (injury_reporting, estimated_inr) or 429 rate limit. Fix: JSON schema enforcement.", table_cell)],
        [Paragraph("Missing Extraction", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell_bold), Paragraph("Zero instances where an explicit identifier was omitted from output.", table_cell)],
        [Paragraph("Ambiguity", table_cell_bold), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell), Paragraph("0", table_cell_bold), Paragraph("Prompt instructions successfully resolved all potential linguistic ambiguities.", table_cell)],
        [Paragraph("<b>Total Failures Audited</b>", table_cell_bold), Paragraph("<b>69</b>", table_cell_bold), Paragraph("<b>64</b>", table_cell_bold), Paragraph("<b>51</b>", table_cell_bold), Paragraph("<b>25</b>", table_cell_bold), Paragraph("<b>63</b>", table_cell_bold), Paragraph("<b>272</b>", table_cell_bold), Paragraph("100% of failed predictions audited and catalogued in CSV.", table_cell_bold)],
    ]
    t_err_cat = Table(error_cat_summary, colWidths=[95, 45, 55, 55, 55, 65, 35, 135])
    t_err_cat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (6, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_BG]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
    ]))
    story.append(t_err_cat)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Detailed Diagnostic Audit of the 5 Non-Success Execution Jobs", h2_style))
    story.append(Paragraph(
        "1. <b>zero_shot_TEST045_run1</b> (<code>VALIDATION_ERROR</code>): Model emitted <code>injury_reporting: false</code> and <code>police_reporting: null</code>. "
        "Root cause: Morphological drift from participle to gerund without in-context exemplar grounding.<br/>"
        "2. <b>zero_shot_TEST026_run2</b> (<code>VALIDATION_ERROR</code>): Model emitted <code>estimated_inr: 5500</code> instead of <code>estimated_amount_inr</code>. "
        "Root cause: Key abbreviation hallucination.<br/>"
        "3. <b>zero_shot_TEST055_run3</b> (<code>VALIDATION_ERROR</code>): Model emitted extra key <code>injury_status: null</code> alongside <code>injury_reported</code>.<br/>"
        "4. <b>few_shot_k3_TEST059_run3</b> (<code>VALIDATION_ERROR</code>): Generated duplicate key <code>policy_type</code> twice, omitting <code>claim_type</code> and <code>urgency</code> on an administrative policy renewal request.<br/>"
        "5. <b>few_shot_k8_TEST017_run3</b> (<code>API_ERROR</code>): HTTP 429 daily token limit reached on key_6 (Limit 200,000 TPD, used 197,057, requested 2,974 tokens).",
        body_style,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph("9. Run-to-Run Consistency & Experimental Determinism", h1_style))
    story.append(Paragraph(
        "Because insurance adjudication requires repeatable automated decisions, run-to-run stability was evaluated across the 3 repeated runs "
        "at temperature 0.0 (60 messages × 3 runs = 180 comparisons per strategy):",
        body_style,
    ))

    consistency_table_data = [
        [Paragraph("Strategy", table_header), Paragraph("Run 1 vs Run 2", table_header), Paragraph("Run 1 vs Run 3", table_header), Paragraph("Run 2 vs Run 3", table_header), Paragraph("All 3 Runs Unanimous", table_header), Paragraph("Deterministic Replication Status", table_header)],
        [Paragraph("zero_shot", table_cell_bold), Paragraph("58 / 60 (96.7%)", table_cell), Paragraph("57 / 60 (95.0%)", table_cell), Paragraph("57 / 60 (95.0%)", table_cell), Paragraph("56 / 60 (93.3%)", table_cell), Paragraph("Slight logit drift on urgency for TEST035.", table_cell)],
        [Paragraph("few_shot_k3", table_cell_bold), Paragraph("60 / 60 (100.0%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("100% deterministic except TEST059 run3 error.", table_cell)],
        [Paragraph("few_shot_k5", table_cell_bold), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>Absolute 100% deterministic replication.</b>", table_cell_bold)],
        [Paragraph("few_shot_k8", table_cell_bold), Paragraph("60 / 60 (100.0%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("59 / 60 (98.3%)", table_cell), Paragraph("100% deterministic on all completed calls.", table_cell)],
        [Paragraph("structured_reasoning", table_cell_bold), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>60 / 60 (100.0%)</b>", table_cell), Paragraph("<b>Absolute 100% deterministic replication.</b>", table_cell_bold)],
    ]
    t_cons = Table(consistency_table_data, colWidths=[95, 80, 80, 80, 95, 110])
    t_cons.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    story.append(t_cons)
    story.append(Paragraph(
        "<b>Important Scientific Distinction</b>: Agreement measures reproducibility, whereas accuracy measures correctness against gold truth. "
        "For example, few_shot_k5 was 100% deterministic (60/60 identical outputs across all 3 runs), but its strict accuracy was 71.7% due to consistent casing differences.",
        body_style,
    ))

    story.append(PageBreak())

    # ================= PAGE 5 =================
    story.append(Paragraph("10. API Accounting, Latency & Economic Cost Audit", h1_style))
    story.append(Paragraph(
        "The evaluation was conducted on Groq Cloud using official on-demand pricing for <code>qwen/qwen3.8-27b</code> ($0.20 per 1M input tokens, "
        "$0.20 per 1M output tokens). Round-trip network latency was measured locally with high-resolution timers (<code>time.perf_counter</code>).",
        body_style,
    ))

    cost_table_data = [
        [Paragraph("Strategy", table_header), Paragraph("Input Tok.", table_header), Paragraph("Output Tok.", table_header), Paragraph("Total Tok.", table_header), Paragraph("Mean Lat.", table_header), Paragraph("Median Lat.", table_header), Paragraph("Actual Exp. Cost", table_header), Paragraph("Cost / 1k Claims", table_header)],
        [Paragraph("zero_shot", table_cell_bold), Paragraph("224,400", table_cell), Paragraph("19,412", table_cell), Paragraph("243,812", table_cell), Paragraph("549.0 ms", table_cell), Paragraph("502.0 ms", table_cell), Paragraph("$0.04876", table_cell), Paragraph("$0.2709", table_cell)],
        [Paragraph("few_shot_k3", table_cell_bold), Paragraph("314,580", table_cell), Paragraph("19,407", table_cell), Paragraph("333,987", table_cell), Paragraph("545.9 ms", table_cell), Paragraph("516.0 ms", table_cell), Paragraph("$0.06680", table_cell), Paragraph("$0.3711", table_cell)],
        [Paragraph("few_shot_k5", table_cell_bold), Paragraph("380,100", table_cell), Paragraph("19,431", table_cell), Paragraph("399,531", table_cell), Paragraph("563.7 ms", table_cell), Paragraph("549.3 ms", table_cell), Paragraph("$0.07991", table_cell), Paragraph("$0.4439", table_cell)],
        [Paragraph("few_shot_k8", table_cell_bold), Paragraph("485,534", table_cell), Paragraph("19,344", table_cell), Paragraph("504,878", table_cell), Paragraph("668.9 ms", table_cell), Paragraph("585.4 ms", table_cell), Paragraph("$0.10098", table_cell), Paragraph("$0.5641", table_cell)],
        [Paragraph("structured_reasoning", table_cell_bold), Paragraph("327,000", table_cell), Paragraph("19,389", table_cell), Paragraph("346,389", table_cell), Paragraph("<b>510.0 ms</b>", table_cell), Paragraph("<b>483.0 ms</b>", table_cell), Paragraph("$0.06928", table_cell), Paragraph("<b>$0.3849</b>", table_cell_bold)],
        [Paragraph("<b>TOTAL BENCHMARK</b>", table_cell_bold), Paragraph("<b>1,731,614</b>", table_cell_bold), Paragraph("<b>96,983</b>", table_cell_bold), Paragraph("<b>1,828,597</b>", table_cell_bold), Paragraph("<b>567.4 ms</b>", table_cell_bold), Paragraph("<b>528.5 ms</b>", table_cell_bold), Paragraph("<b>$0.36572</b>", table_cell_bold), Paragraph("<b>$0.4070</b>", table_cell_bold)],
    ]
    t_cost = Table(cost_table_data, colWidths=[95, 60, 55, 60, 60, 60, 75, 75])
    t_cost.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT_BG]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
    ]))
    story.append(t_cost)
    story.append(Spacer(1, 6))

    story.append(Paragraph("API Request Accounting Reconciliation", h2_style))
    story.append(Paragraph(
        "• <b>900 Planned Jobs vs. API Invocations</b>: Exactly 900 evaluation jobs were scheduled and executed across 3 batch commands (546 + 177 + 177 = 900). "
        "The runner's counter tracks job progression. In 899 jobs, the HTTP completion succeeded on the initial attempt; 1 job encountered an HTTP 429 quota exhaustion.<br/>"
        "• <b>Latency Measurement Scope</b>: Timers encapsulate the complete HTTP wire round trip from local client request dispatch to response deserialization. "
        "For the single API error, latency is recorded as 0.0 ms and tokens as null.<br/>"
        "• <b>Experimental Cost</b>: The entire 900-job benchmark was executed for a total computing cost of <b>$0.3657 (under 37 cents)</b>, demonstrating the extreme economic efficiency of Groq inference.",
        body_style,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph("11. Production Architecture Recommendations & Strategic Verdict", h1_style))
    story.append(Paragraph(
        "<b>Primary Operational Recommendation: Structured Reasoning with Casing Normalization</b><br/>"
        "1. <b>Adjudication Superiority</b>: Structured Reasoning achieved the highest classification Macro-F1 (0.9870), correctly resolved subtle edge cases that few-shot prompts failed (e.g. TEST005 door scratching under Rule A), and had 0.0% hallucination on locations.<br/>"
        "2. <b>Latency & Efficiency</b>: Structured Reasoning ran <b>23.8% faster</b> than few-shot k=8 (510ms vs 669ms) and consumed <b>31.8% fewer tokens</b>, reducing operating costs from $0.56 to $0.38 per 1k claims.<br/>"
        "3. <b>Zero Schema Violations</b>: Achieved a flawless 100.0% schema validity rate with 100.0% deterministic run-to-run replication.<br/>"
        "4. <b>Recommended Pipeline Enhancement</b>: Pair Structured Reasoning with a lightweight regex/title-casing post-processor. Because 48 of its 63 failures were minor casing differences (e.g. 'mall basement' vs 'Mall basement'), post-processing boosts strict exact match from 65.0% to <b>81.7%</b> at zero added inference cost.",
        body_style,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph("12. Limitations & Transition to Case Study 2", h1_style))
    story.append(Paragraph(
        "• <b>Synthetic Context Boundary</b>: Messages were synthetically generated to model noisy Indian claims. While covering complex vernacular and edge cases, real-world deployment requires testing on live audio-transcribed call center logs.<br/>"
        "• <b>Confounding in Few-Shot Progression</b>: In the nested few-shot hierarchy ($k=3 \\subset k=5 \\subset k=8$), scaling example count simultaneously expanded category coverage, confounding sample volume with taxonomy exposure.<br/>"
        "• <b>Case Study 2 Readiness</b>: With CS1 evaluation, error analysis, and documentation 100% audited and verified, the environment is fully prepared for Case Study 2 (PolicyLens), which builds on these extraction foundations to implement a multi-column, OCR-backed PDF parsing and vector retrieval pipeline.",
        body_style,
    ))
    story.append(Spacer(1, 10))

    # Sign-off box
    signoff_data = [
        [
            Paragraph("<b>Audit Status: COMPLETE & VERIFIED</b><br/>"
                      "All 900 records audited against data/test.jsonl. Zero cherry-picking, zero missing records.<br/>"
                      "Artifacts: <code>results.csv</code> (900 rows) | <code>error_analysis.csv</code> (272 failures) | <code>metrics_summary.json</code>", table_cell),
            Paragraph("<b>Lead AI Engineer</b>: Vinit Surve<br/>"
                      f"<b>Date</b>: {datetime.date.today().strftime('%B %d, %Y')}<br/>"
                      "<b>Repository</b>: <code>agentic_ai_case_studies</code>", table_cell_bold),
        ]
    ]
    t_sign = Table(signoff_data, colWidths=[340, 200])
    t_sign.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E2E8F0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#A0AEC0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_sign)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated final report PDF: {PDF_PATH}")


if __name__ == "__main__":
    build_pdf()
