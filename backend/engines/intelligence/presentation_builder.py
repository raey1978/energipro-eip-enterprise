"""
EIP v6.3 — Executive Presentation Builder
Generates a branded PowerPoint presentation from live market intelligence.

Brand: EnergiPro Solutions
  - Navy:   #1A4A5C  (primary dark)
  - Teal:   #1F6460  (secondary)
  - Orange: #E07820  (accent)
  - White:  #FFFFFF
  - Light:  #F4F6FB  (backgrounds)

Slide structure (9 slides):
  1. Cover — company + report date + sub-title
  2. Executive Summary — 6 KPI tiles
  3. Market Pulse — period comparison table + activity index
  4. Market Changes — top 5 changes with severity
  5. Opportunities — top 6 ranked by commercial priority
  6. Competitor Intelligence — heat map table
  7. Active Campaigns — campaign tracker
  8. Revenue Pipeline — weighted pipeline by product line
  9. Intelligence Quality — 7-dimension quality score
"""
from __future__ import annotations
import io, datetime, json
from typing import Optional


def build_presentation(
    market_data: dict,
    company_name: str = "EnergiPro Solutions",
    report_date: str = "",
) -> io.BytesIO:
    """
    Build a complete executive presentation from market intelligence data.
    Returns an in-memory BytesIO of the .pptx file.
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    # ── Brand colours ─────────────────────────────────────────────────────────
    NAVY   = RGBColor(0x1A, 0x4A, 0x5C)
    TEAL   = RGBColor(0x1F, 0x64, 0x60)
    ORANGE = RGBColor(0xE0, 0x78, 0x20)
    WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
    LIGHT  = RGBColor(0xF4, 0xF6, 0xFB)
    GREEN  = RGBColor(0x10, 0xB9, 0x81)
    RED    = RGBColor(0xEF, 0x44, 0x44)
    AMBER  = RGBColor(0xF5, 0x9E, 0x0B)
    GREY   = RGBColor(0x64, 0x74, 0x8B)
    DGREY  = RGBColor(0x1E, 0x2D, 0x45)

    today     = report_date or datetime.date.today().strftime("%d %B %Y")
    gen_ts    = datetime.date.today().strftime("%d %B %Y")

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # Helper shortcuts
    def add_slide(layout_idx=6):
        layout = prs.slide_layouts[layout_idx]  # blank
        return prs.slides.add_slide(layout)

    def rgb(r,g,b): return RGBColor(r,g,b)

    def rect(slide, x, y, w, h, fill_rgb, alpha=None):
        from pptx.util import Inches
        shape = slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Inches(h))
        shape.line.fill.background()
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_rgb
        return shape

    def text_box(slide, x, y, w, h, text, size=18, bold=False,
                 color=WHITE, align=PP_ALIGN.LEFT, wrap=True):
        txb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf  = txb.text_frame
        tf.word_wrap = wrap
        p   = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = "Calibri"
        return txb

    def fv(v):
        if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
        if v >= 1_000:     return f"${v/1_000:.0f}K"
        return f"${v:.0f}"

    def header_bar(slide, title, subtitle=""):
        """Standard header bar for all content slides."""
        rect(slide, 0, 0, 13.33, 1.0, NAVY)
        text_box(slide, 0.3, 0.08, 10, 0.5, title, size=24, bold=True, color=WHITE)
        if subtitle:
            text_box(slide, 0.3, 0.58, 11, 0.35, subtitle, size=11, color=LIGHT)
        rect(slide, 0, 1.0, 13.33, 0.05, ORANGE)
        # Footer
        rect(slide, 0, 7.2, 13.33, 0.3, DGREY)
        text_box(slide, 0.2, 7.22, 8, 0.25,
                 f"{company_name} — AI Market Intelligence | EIP v6.3 | {gen_ts} | CONFIDENTIAL",
                 size=8, color=GREY)

    # Collect data
    opps      = market_data.get("opportunities", [])
    comps     = market_data.get("competitors", [])
    from engines.intelligence.market_intelligence import get_market_pulse, get_market_aggregates
    from engines.intelligence.change_detection    import get_change_feed
    from engines.intelligence.campaign_detector   import get_campaigns
    from engines.intelligence.governance_layer    import compute_intelligence_quality
    from engines.intelligence.commercial_engine   import calculate_commercial_intelligence
    from collections import Counter

    pulse   = get_market_pulse()
    agg     = get_market_aggregates()
    changes = get_change_feed(limit=5)
    camps   = get_campaigns()[:4]
    quality = compute_intelligence_quality()
    M       = pulse.get("metrics", {})

    imm_opps = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
    total_pl  = sum(o.get("estimated_value",0) for o in opps)

    # Enrich top opportunities with commercial scores
    top_opps = []
    for opp in sorted(opps, key=lambda x: -x.get("confidence",0))[:6]:
        try:
            ci = calculate_commercial_intelligence(opp)
            top_opps.append({**opp, "ci": ci})
        except Exception:
            top_opps.append({**opp, "ci": {}})

    # ── Slide 1: Cover ────────────────────────────────────────────────────────
    s1 = add_slide()
    rect(s1, 0, 0, 13.33, 7.5, NAVY)
    rect(s1, 0, 0, 13.33, 7.5, NAVY)
    # Orange accent bar
    rect(s1, 0, 5.8, 13.33, 0.12, ORANGE)
    # Left accent stripe
    rect(s1, 0, 0, 0.15, 7.5, TEAL)

    text_box(s1, 0.5, 1.2, 12, 1.0, company_name, size=36, bold=True, color=WHITE)
    text_box(s1, 0.5, 2.3, 12, 0.7,
             "AI Market Intelligence & Revenue Intelligence Platform",
             size=20, color=LIGHT)
    text_box(s1, 0.5, 3.2, 12, 0.5,
             "Executive Intelligence Presentation", size=16, color=ORANGE)
    text_box(s1, 0.5, 4.0, 12, 0.4,
             f"Report Date: {today}", size=13, color=LIGHT)
    text_box(s1, 0.5, 4.5, 12, 0.4,
             f"Generated: {gen_ts} | EIP DDR Intelligence v6.3",
             size=11, color=rgb(0x94,0xA3,0xB8))
    text_box(s1, 0.5, 6.8, 12, 0.35,
             "CONFIDENTIAL — For authorised recipients only",
             size=10, color=rgb(0x94,0xA3,0xB8))

    # ── Slide 2: Executive Summary KPIs ──────────────────────────────────────
    s2 = add_slide()
    rect(s2, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s2, "Executive Summary",
               f"{len(opps)} opportunities · {len(imm_opps)} immediate · {fv(total_pl)} pipeline")

    kpis = [
        ("Active Rigs",   str(M.get("active_rigs",{}).get("current","—")),   NAVY,  0.3),
        ("Opportunities", str(M.get("total_opps",{}).get("current","—")),     TEAL,  2.55),
        ("Immediate",     str(len(imm_opps)),                                  RED,   4.8),
        ("Pipeline",      fv(total_pl),                                        GREEN, 7.05),
        ("Competitors",   str(M.get("competitor_density",{}).get("current","—")), rgb(0x63,0x66,0xF1), 9.3),
        ("Quality Score", f"{quality.get('composite_score',0)}/100",           ORANGE, 11.05),
    ]
    for label, value, color, x in kpis:
        rect(s2, x, 1.3, 2.0, 2.2, color)
        text_box(s2, x, 1.4, 2.0, 1.1, value, size=34, bold=True,
                 color=WHITE, align=PP_ALIGN.CENTER)
        text_box(s2, x, 2.55, 2.0, 0.5, label, size=11,
                 color=WHITE, align=PP_ALIGN.CENTER)

    # Summary text
    rect(s2, 0.3, 3.8, 12.7, 1.8, WHITE)
    summary_text = (
        f"The platform has identified {len(opps)} commercial opportunities with "
        f"{fv(total_pl)} in potential pipeline value. "
        f"{len(imm_opps)} opportunities require immediate or 5-day action. "
        f"Overall intelligence quality is {quality.get('composite_score',0)}/100 "
        f"({quality.get('grade_label','—')}), based on "
        f"{agg.get('uploads_processed',0)} DDR report(s) covering "
        f"{agg.get('unique_rigs',0)} rig(s) across {agg.get('unique_fields',0)} field(s)."
    )
    text_box(s2, 0.5, 3.95, 12.3, 1.5, summary_text, size=12, color=DGREY)

    # ── Slide 3: Market Pulse ─────────────────────────────────────────────────
    s3 = add_slide()
    rect(s3, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s3, "Market Pulse",
               f"Period comparison: {pulse.get('current_period','—')} vs {pulse.get('previous_period','no previous')}")

    def _pct(m):
        p = m.get("change_pct") if isinstance(m,dict) else None
        if p is None: return "First report"
        arrow = "↑" if p>0 else "↓" if p<0 else "→"
        return f"{arrow} {abs(p):.0f}%"
    def _cur(m):
        return str(m.get("current","—")) if isinstance(m,dict) else "—"

    metrics = [
        ("Active Rigs",     M.get("active_rigs",{})),
        ("Active Fields",   M.get("active_fields",{})),
        ("Opportunities",   M.get("total_opps",{})),
        ("Immediate Actions",M.get("immediate_opps",{})),
        ("Pipeline Value",  M.get("pipeline",{})),
        ("Activity Index",  M.get("activity_intensity",{})),
    ]

    # Table
    rect(s3, 0.3, 1.2, 9.0, 0.45, NAVY)
    for j, hdr in enumerate(["Metric","Current","vs Previous"]):
        xp = 0.35 + j*3.0
        text_box(s3, xp, 1.25, 2.8, 0.35, hdr, size=11, bold=True,
                 color=WHITE, align=PP_ALIGN.CENTER)
    for i, (label, m) in enumerate(metrics):
        bg = LIGHT if i%2==0 else WHITE
        rect(s3, 0.3, 1.65+i*0.55, 9.0, 0.52, bg)
        text_box(s3, 0.35, 1.67+i*0.55, 2.8, 0.45, label, size=11, color=DGREY)
        cur_val = _cur(m)
        if label == "Pipeline Value":
            try: cur_val = fv(float(cur_val)) if cur_val!="—" else "—"
            except: pass
        text_box(s3, 3.35, 1.67+i*0.55, 2.8, 0.45, cur_val,
                 size=13, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
        pct_text = _pct(m)
        pct_color = GREEN if "↑" in pct_text else RED if "↓" in pct_text else GREY
        text_box(s3, 6.35, 1.67+i*0.55, 2.8, 0.45, pct_text,
                 size=12, bold=True, color=pct_color, align=PP_ALIGN.CENTER)

    # Activity bar
    ai = M.get("activity_intensity",{}).get("current",0) or 0
    text_box(s3, 9.7, 1.3, 3.3, 0.4, "Activity Index", size=12, bold=True, color=NAVY)
    rect(s3, 9.7, 1.75, 3.3, 0.5, rgb(0xE2,0xE8,0xF0))
    bar_w = min(3.3, 3.3 * (ai/100))
    bar_c = GREEN if ai>=70 else AMBER if ai>=40 else RED
    rect(s3, 9.7, 1.75, bar_w, 0.5, bar_c)
    text_box(s3, 9.7, 1.78, 3.3, 0.45, f"{ai}/100", size=13, bold=True,
             color=WHITE, align=PP_ALIGN.CENTER)

    # PL distribution
    if pulse.get("product_line_pulse"):
        text_box(s3, 9.7, 2.5, 3.3, 0.35, "Top Product Lines", size=11, bold=True, color=NAVY)
        for i, pl_item in enumerate(pulse["product_line_pulse"][:5]):
            pl_label = pl_item.get("product_line","")[:20]
            cnt = pl_item.get("count",0)
            direction = pl_item.get("direction","→")
            text_box(s3, 9.7, 2.9+i*0.45, 3.3, 0.4,
                     f"{direction} {pl_label}: {cnt}",
                     size=10, color=DGREY)

    # ── Slide 4: Market Changes ───────────────────────────────────────────────
    s4 = add_slide()
    rect(s4, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s4, "What Changed?",
               f"{len(changes)} market changes detected — auto-identified between DDR uploads")

    sev_color = {"critical": RED, "high": AMBER, "medium": rgb(0x37,0x99,0xEB), "info": GREEN}

    if not changes:
        rect(s4, 0.5, 1.5, 12.3, 2.0, WHITE)
        text_box(s4, 0.5, 2.1, 12.3, 0.8,
                 "No changes detected yet. Upload multiple DDR reports to enable change detection.",
                 size=14, color=GREY, align=PP_ALIGN.CENTER)
    else:
        for i, ch in enumerate(changes[:5]):
            y_start = 1.25 + i * 1.05
            sev  = ch.get("severity","info")
            color = sev_color.get(sev, GREY)
            rect(s4, 0.3, y_start, 12.7, 0.95, WHITE)
            rect(s4, 0.3, y_start, 0.08, 0.95, color)
            text_box(s4, 0.5, y_start+0.02, 10, 0.4,
                     ch.get("title","")[:100], size=12, bold=True, color=DGREY)
            text_box(s4, 0.5, y_start+0.42, 10, 0.45,
                     (ch.get("recommended_action","") or ch.get("summary",""))[:120],
                     size=10, color=GREY)
            text_box(s4, 10.8, y_start+0.1, 2.3, 0.4,
                     sev.upper(), size=11, bold=True,
                     color=color, align=PP_ALIGN.RIGHT)

    # ── Slide 5: Top Opportunities ────────────────────────────────────────────
    s5 = add_slide()
    rect(s5, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s5, "Top Commercial Opportunities",
               f"Ranked by Commercial Priority | {len(imm_opps)} immediate actions required")

    urg_map = {"immediate":"NOW","5_days":"5 DAYS","7_days":"7 DAYS","30_days":"30 DAYS","future":"FUTURE"}
    urg_col = {"immediate":RED,"5_days":AMBER,"7_days":rgb(0x37,0x99,0xEB),"30_days":rgb(0x63,0x66,0xF1),"future":GREY}

    if not top_opps:
        text_box(s5, 0.5, 2.5, 12.3, 0.8,
                 "No opportunities detected. Upload a DDR to generate intelligence.",
                 size=14, color=GREY, align=PP_ALIGN.CENTER)
    else:
        cols = ["#","Product Line","Rig / Well","Urgency","Conf","Value","Competitor"]
        col_w = [0.4, 2.4, 2.0, 1.2, 0.8, 1.4, 2.0]
        col_x = [0.3]
        for w in col_w[:-1]: col_x.append(col_x[-1]+w+0.05)

        rect(s5, 0.3, 1.2, 12.7, 0.45, NAVY)
        for j, (hdr, x) in enumerate(zip(cols, col_x)):
            text_box(s5, x, 1.25, col_w[j], 0.35, hdr, size=10, bold=True,
                     color=WHITE, align=PP_ALIGN.CENTER)

        for i, opp in enumerate(top_opps[:6]):
            ci  = opp.get("ci",{})
            urg = opp.get("urgency","future")
            bg  = LIGHT if i%2==0 else WHITE
            y   = 1.65 + i*0.82
            rect(s5, 0.3, y, 12.7, 0.78, bg)

            row_vals = [
                (str(i+1),     PP_ALIGN.CENTER),
                ((opp.get("product_line","") or "")[:22],   PP_ALIGN.LEFT),
                (f"{opp.get('rig','—')}/{opp.get('well','—')}"[:22], PP_ALIGN.LEFT),
                (urg_map.get(urg,"—"),  PP_ALIGN.CENTER),
                (f"{opp.get('confidence',0)}%", PP_ALIGN.CENTER),
                (fv(opp.get("estimated_value",0) or 0), PP_ALIGN.RIGHT),
                ((opp.get("competitor","None") or "—")[:20], PP_ALIGN.LEFT),
            ]
            for j, ((val, align_v), x, w) in enumerate(zip(row_vals, col_x, col_w)):
                c = urg_col.get(urg,GREY) if j==3 else (GREEN if j==4 and opp.get("confidence",0)>=80 else RED if j==4 else (RED if j==6 and opp.get("competitor") else GREEN if j==6 else DGREY))
                text_box(s5, x, y+0.22, w, 0.45, val, size=10, color=c,
                         bold=(j in (0,4)), align=align_v)

            # Priority bar
            pri = ci.get("commercial_priority",0) or 0
            rect(s5, col_x[-1], y+0.0, col_w[-1], 0.15,
                 rgb(0xE2,0xE8,0xF0))
            bar_c = GREEN if pri>=70 else AMBER if pri>=50 else RED
            rect(s5, col_x[-1], y+0.0, col_w[-1]*pri/100, 0.15, bar_c)

    # ── Slide 6: Competitor Intelligence ─────────────────────────────────────
    s6 = add_slide()
    rect(s6, 0, 0, 13.33, 7.5, LIGHT)
    comp_counts = Counter(c.get("normalized","") for c in comps if c.get("normalized"))
    header_bar(s6, "Competitor Intelligence",
               f"{len(comp_counts)} competitors detected · {len(comps)} total detections")

    if not comp_counts:
        rect(s6, 0.5, 1.5, 12.3, 2.0, WHITE)
        text_box(s6, 0.5, 2.1, 12.3, 0.8,
                 "No competitors detected. Upload DDRs with SC company codes to enable competitor tracking.",
                 size=14, color=GREY, align=PP_ALIGN.CENTER)
    else:
        max_count = max(comp_counts.values())
        cols = ["Company","Detections","Rigs Present","Market Share","Threat Level"]
        col_w = [2.8,1.5,2.2,3.5,1.8]
        col_x = [0.3]
        for w in col_w[:-1]: col_x.append(col_x[-1]+w+0.1)

        rect(s6, 0.3, 1.2, 12.4, 0.45, TEAL)
        for j,(hdr,x,w) in enumerate(zip(cols,col_x,col_w)):
            text_box(s6,x,1.25,w,0.35,hdr,size=10,bold=True,color=WHITE)

        for i,(comp,count) in enumerate(comp_counts.most_common(7)):
            y   = 1.65 + i*0.72
            bg  = LIGHT if i%2==0 else WHITE
            rect(s6,0.3,y,12.4,0.68,bg)
            # Company
            text_box(s6,col_x[0],y+0.15,col_w[0],0.45,comp,size=11,bold=True,color=NAVY)
            # Count
            text_box(s6,col_x[1],y+0.15,col_w[1],0.45,str(count),size=13,bold=True,
                     color=RED,align=PP_ALIGN.CENTER)
            # Rig count
            rig_set = set(c.get("rig","") for c in comps if c.get("normalized")==comp and c.get("rig"))
            text_box(s6,col_x[2],y+0.15,col_w[2],0.45,str(len(rig_set)),size=11,
                     color=DGREY,align=PP_ALIGN.CENTER)
            # Market share bar
            share = count/max(max_count,1)
            rect(s6,col_x[3],y+0.2,col_w[3],0.28,rgb(0xE2,0xE8,0xF0))
            rect(s6,col_x[3],y+0.2,col_w[3]*share,0.28,RED)
            text_box(s6,col_x[3],y+0.2,col_w[3],0.28,
                     f"{round(count/sum(comp_counts.values())*100)}%",
                     size=9,color=WHITE,align=PP_ALIGN.CENTER)
            # Threat
            threat = "HIGH" if count>=8 else "MEDIUM" if count>=4 else "LOW"
            tc = RED if threat=="HIGH" else AMBER if threat=="MEDIUM" else GREEN
            text_box(s6,col_x[4],y+0.15,col_w[4],0.45,threat,size=10,bold=True,
                     color=tc,align=PP_ALIGN.CENTER)

    # ── Slide 7: Active Campaigns ─────────────────────────────────────────────
    s7 = add_slide()
    rect(s7, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s7, "Active Drilling Campaigns",
               f"{len(camps)} campaigns detected — auto-grouped by field co-location")

    if not camps:
        rect(s7, 0.5, 1.5, 12.3, 2.0, WHITE)
        text_box(s7, 0.5, 2.1, 12.3, 0.8,
                 "No campaigns detected. Campaigns appear when multiple rigs are active in the same field.",
                 size=14, color=GREY, align=PP_ALIGN.CENTER)
    else:
        for i, camp in enumerate(camps[:4]):
            rigs   = camp.get("rigs",[]) if isinstance(camp.get("rigs"),list) else []
            svc    = camp.get("expected_services",[]) if isinstance(camp.get("expected_services"),list) else []
            fields = camp.get("fields",[]) if isinstance(camp.get("fields"),list) else []
            x_start = 0.3 + (i%2)*6.6
            y_start = 1.25 + (i//2)*2.8
            rect(s7, x_start, y_start, 6.3, 2.6, WHITE)
            rect(s7, x_start, y_start, 6.3, 0.45, TEAL)
            text_box(s7, x_start+0.1, y_start+0.06, 5.5, 0.35,
                     camp.get("name","")[:40], size=12, bold=True, color=WHITE)
            conf = camp.get("confidence",0)
            text_box(s7, x_start+5.5, y_start+0.06, 0.7, 0.35,
                     f"{conf}%", size=10, color=LIGHT, align=PP_ALIGN.RIGHT)
            # Metrics
            text_box(s7, x_start+0.15, y_start+0.55, 2.8, 0.35,
                     f"Rigs: {len(rigs)}", size=11, color=DGREY)
            text_box(s7, x_start+3.0, y_start+0.55, 3.1, 0.35,
                     f"Value: {fv(camp.get('estimated_market_value',0) or 0)}",
                     size=11, bold=True, color=GREEN)
            text_box(s7, x_start+0.15, y_start+0.9, 6.0, 0.35,
                     f"Field: {', '.join(fields[:2])} | Stage: {(camp.get('campaign_stage','') or '').replace('_',' ').title()}",
                     size=10, color=GREY)
            text_box(s7, x_start+0.15, y_start+1.25, 6.0, 0.35,
                     f"Rigs: {', '.join(rigs[:3])}{'…' if len(rigs)>3 else ''}",
                     size=9, color=GREY)
            text_box(s7, x_start+0.15, y_start+1.6, 6.0, 0.35,
                     f"Services: {', '.join(svc[:3])}",
                     size=9, color=DGREY)
            text_box(s7, x_start+0.15, y_start+1.95, 6.0, 0.35,
                     f"Est. duration: {camp.get('estimated_duration_weeks',0)} weeks",
                     size=9, color=GREY)

    # ── Slide 8: Revenue Pipeline ─────────────────────────────────────────────
    s8 = add_slide()
    rect(s8, 0, 0, 13.33, 7.5, LIGHT)
    from engines.intelligence.revenue_engine import build_revenue_pipeline_summary
    rev_sum = build_revenue_pipeline_summary(opps)
    header_bar(s8, "Revenue Pipeline",
               f"Expected: {fv(rev_sum.get('pipeline_expected',0))} | Weighted: {fv(rev_sum.get('pipeline_weighted',0))} | Avg Margin: {rev_sum.get('avg_margin_pct',0)}%")

    # Summary KPIs
    kpi_items = [
        ("Expected Pipeline",     fv(rev_sum.get("pipeline_expected",0)),    NAVY),
        ("Weighted Pipeline",     fv(rev_sum.get("pipeline_weighted",0)),     GREEN),
        ("Conservative",          fv(rev_sum.get("pipeline_conservative",0)), GREY),
        ("Optimistic",            fv(rev_sum.get("pipeline_optimistic",0)),   TEAL),
        ("Total Gross Margin",    fv(rev_sum.get("total_gross_margin",0)),    ORANGE),
        ("Avg Margin %",          f"{rev_sum.get('avg_margin_pct',0)}%",      AMBER),
    ]
    for j,(label,val,color) in enumerate(kpi_items):
        x = 0.3 + j*2.15
        rect(s8,x,1.2,1.98,1.0,WHITE)
        rect(s8,x,1.2,1.98,0.12,color)
        text_box(s8,x+0.05,1.35,1.88,0.55,val,size=18,bold=True,
                 color=DGREY,align=PP_ALIGN.CENTER)
        text_box(s8,x+0.05,1.9,1.88,0.28,label,size=9,
                 color=GREY,align=PP_ALIGN.CENTER)

    # PL table
    by_pl = rev_sum.get("by_product_line",[])[:7]
    if by_pl:
        rect(s8,0.3,2.45,12.7,0.4,NAVY)
        for j,hdr in enumerate(["Product Line","Items","Expected","Weighted","Margin"]):
            text_box(s8,0.35+j*2.55,2.5,2.5,0.3,hdr,size=10,bold=True,
                     color=WHITE,align=PP_ALIGN.CENTER)
        for i,pl in enumerate(by_pl):
            y=2.85+i*0.55; bg=LIGHT if i%2==0 else WHITE
            rect(s8,0.3,y,12.7,0.52,bg)
            margin_val = round(pl.get("expected",0)*0.28) if pl.get("expected",0)>0 else 0
            for j,(val,align_v) in enumerate([
                (pl.get("product_line","")[:28],PP_ALIGN.LEFT),
                (str(pl.get("count",0)),PP_ALIGN.CENTER),
                (fv(pl.get("expected",0)),PP_ALIGN.RIGHT),
                (fv(pl.get("weighted",0)),PP_ALIGN.RIGHT),
                (fv(margin_val),PP_ALIGN.RIGHT),
            ]):
                c = GREEN if j==3 else ORANGE if j==4 else DGREY
                text_box(s8,0.35+j*2.55,y+0.12,2.5,0.35,val,size=10,
                         color=c,bold=(j==0),align=align_v)

    text_box(s8,0.3,6.95,12.7,0.22,
             "Weighted pipeline = Expected Revenue × Win Probability. Values are estimates based on Saudi Aramco unit-rate benchmarks.",
             size=8,color=GREY)

    # ── Slide 9: Intelligence Quality ─────────────────────────────────────────
    s9 = add_slide()
    rect(s9, 0, 0, 13.33, 7.5, LIGHT)
    header_bar(s9, "Intelligence Quality Assessment",
               f"Overall Score: {quality.get('composite_score',0)}/100 ({quality.get('grade_label','—')})")

    grade = quality.get("grade","D")
    grade_color = {"A":GREEN,"B":rgb(0x06,0xB6,0xD4),"C":AMBER,"D":RED}.get(grade,GREY)

    # Big grade
    rect(s9, 0.3, 1.2, 2.5, 2.5, WHITE)
    text_box(s9, 0.3, 1.25, 2.5, 1.5, grade, size=72, bold=True,
             color=grade_color, align=PP_ALIGN.CENTER)
    text_box(s9, 0.3, 2.65, 2.5, 0.5,
             f"{quality.get('composite_score',0)}/100", size=16, bold=True,
             color=DGREY, align=PP_ALIGN.CENTER)
    text_box(s9, 0.3, 3.15, 2.5, 0.4, quality.get("grade_label",""),
             size=12, color=GREY, align=PP_ALIGN.CENTER)

    # 7 dimension bars
    dims = quality.get("dimension_scores",{})
    weights = quality.get("weights",{})
    for i,(dim,score) in enumerate(dims.items()):
        y = 1.2 + i*0.72
        wt = round(weights.get(dim,0)*100)
        label = dim.replace("_"," ").title()
        rect(s9, 3.0, y, 9.8, 0.6, WHITE)
        text_box(s9, 3.05, y+0.08, 3.5, 0.4, f"{label} ({wt}%)", size=10, color=DGREY)
        # bar background
        rect(s9, 6.7, y+0.15, 5.5, 0.3, rgb(0xE2,0xE8,0xF0))
        bar_color = GREEN if score>=70 else AMBER if score>=50 else RED
        bar_w = max(0.05, 5.5*score/100)
        rect(s9, 6.7, y+0.15, bar_w, 0.3, bar_color)
        text_box(s9, 12.3, y+0.1, 0.8, 0.4, f"{score}", size=11, bold=True,
                 color=bar_color, align=PP_ALIGN.CENTER)

    # Counts
    rc = quality.get("raw_counts",{})
    text_box(s9, 0.3, 6.45, 12.7, 0.4,
             f"Coverage: {rc.get('unique_rigs',0)} rigs · {rc.get('unique_fields',0)} fields · "
             f"{rc.get('unique_competitors',0)} competitors · {rc.get('uploads_processed',0)} reports · "
             f"{rc.get('validated_opps',0)} validated opportunities",
             size=10, color=GREY)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
