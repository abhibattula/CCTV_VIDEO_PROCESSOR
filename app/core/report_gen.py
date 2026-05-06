"""
ReportLab PDF report generator.
Writes to a temp file on disk — never buffers in BytesIO (research Decision 9).
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

from app.config import JOBS_DIR
from app.core.analytics import compute
from app.database import get_conn


def generate(job_id: str) -> str:
    """Generate PDF report to disk. Returns file path string."""
    conn = get_conn()
    job_row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job_row:
        raise ValueError(f"Job {job_id} not found")

    analytics = compute(job_id)
    events = conn.execute(
        "SELECT * FROM events WHERE job_id=? AND included=1 ORDER BY start_s",
        (job_id,),
    ).fetchall()

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pdf_path = str(job_dir / f"report_{ts}.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    # Cover page
    story.append(Paragraph("RasPi CCTV Analyst — Analysis Report", styles["Title"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Job ID: {job_id}", styles["Normal"]))
    story.append(Paragraph(f"Source: {job_row['source_name']}", styles["Normal"]))
    story.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    story.append(Paragraph(f"RAM mode: {job_row.get('ram_mode','2gb') if hasattr(job_row,'ram_mode') else '2gb'}", styles["Normal"]))
    story.append(Spacer(1, 1*cm))

    # Summary stats table
    story.append(Paragraph("Summary", styles["Heading2"]))
    summary_data = [
        ["Metric", "Value"],
        ["Total Events", str(analytics["total_events"])],
        ["Included Events", str(analytics["included_events"])],
        ["Activity %", f"{analytics['activity_percent']:.1f}%"],
        ["Peak Hour", str(analytics["peak_hour"]) if analytics["peak_hour"] is not None else "N/A"],
        ["Longest Event", f"{analytics['longest_event_s']:.1f}s"],
        ["Avg Event Duration", f"{analytics['avg_event_s']:.1f}s"],
    ]
    t = Table(summary_data, colWidths=[8*cm, 8*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 1*cm))

    # Hourly activity table (ReportLab VerticalBarChart would need special import)
    story.append(Paragraph("Hourly Activity", styles["Heading2"]))
    if analytics["hourly_activity"]:
        hour_data = [["Hour", "Events", "Total Duration (s)"]]
        for row in analytics["hourly_activity"]:
            hour_data.append([
                f"{row['hour']:02d}:00",
                str(row["event_count"]),
                f"{row['total_duration_s']:.0f}s",
            ])
        ht = Table(hour_data, colWidths=[5*cm, 5*cm, 7*cm])
        ht.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(ht)
    else:
        story.append(Paragraph("No activity data.", styles["Normal"]))
    story.append(Spacer(1, 1*cm))

    # Event log table (10 rows/page)
    story.append(Paragraph("Event Log (Included Events)", styles["Heading2"]))
    if events:
        ev_data = [["#", "Start", "End", "Duration", "Tag"]]
        for i, ev in enumerate(events):
            ev_data.append([
                str(i + 1),
                ev["start_clock"] or f"{float(ev['start_s']):.1f}s",
                ev["end_clock"] or f"{float(ev['end_s']):.1f}s",
                f"{float(ev['duration_s']):.1f}s",
                ev["tag"] or "—",
            ])
        ev_t = Table(ev_data, colWidths=[1.5*cm, 4*cm, 4*cm, 3.5*cm, 4*cm])
        ev_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(ev_t)

    doc.build(story)
    return pdf_path
