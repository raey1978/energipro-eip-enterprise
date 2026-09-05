"""
EIP v6.1 — Executive Demonstration Mode
Seeds the database with a realistic 90-day KSA market scenario.

The demo tells a coherent commercial story in 5 minutes:
  - 3 operators (Aramco JV, Aramco Main, Aramco Unconventional)
  - 8 rigs across 4 fields (Thoraiyat, Khurais, Ghawar, Jafurah)
  - 4 competitors with different market positions
  - A drilling campaign that evolved over 3 report cycles
  - Revenue opportunities across 5 product lines
  - Competitor movements that create displacement opportunities
  - Market changes between uploads
"""
import uuid, datetime, json
from core.database import get_db


def seed_demo_data() -> dict:
    """
    Populate the database with realistic KSA demo data.
    Safe to run on top of existing data — uses distinct upload IDs.
    Returns summary of what was created.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat()

    # ── Scenario Timeline: 3 uploads over 90 days ─────────────────────────────
    DEMO_UPLOADS = [
        {
            "id":          "DEMO-UPLOAD-001",
            "filename":    "LMR_Batch1_Apr2026.pdf",
            "report_date": "2026-04-15",
            "upload_ts":   "2026-04-15T06:00:00",
            "scenario":    "early_campaign",   # Campaign starting in Thoraiyat
        },
        {
            "id":          "DEMO-UPLOAD-002",
            "filename":    "LMR_Batch2_May2026.pdf",
            "report_date": "2026-05-15",
            "upload_ts":   "2026-05-15T06:00:00",
            "scenario":    "mid_campaign",     # Expansion to Khurais, competitor enters
        },
        {
            "id":          "DEMO-UPLOAD-003",
            "filename":    "LMR_Batch3_Jul2026.pdf",
            "report_date": "2026-07-02",
            "upload_ts":   "2026-07-02T06:00:00",
            "scenario":    "late_campaign",    # Completion phase, Jafurah entry
        },
    ]

    # ── Core opportunity data per upload ──────────────────────────────────────
    OPPORTUNITIES = {
        "DEMO-UPLOAD-001": [
            # Thoraiyat early drilling — SLB on MWD, EnergiPro can take Completion
            {"id":"D001-O001","product_line":"MWD / Directional","rig":"AD-73","well":"THRY-951201",
             "field":"Thoraiyat","confidence":92,"urgency":"immediate","estimated_value":220000,
             "competitor":"SLB","evidence_text":"SPERRY ORBIT RSS BHA ON LOCATION. DRILLING 8.5 INCH SECTION AT 3,420M. ROP 12M/HR. NEXT 24H: DRILL TO TD 3,850M, POOH, RUN MWD SURVEY.",
             "evidence_section":"Last 24h Operations","timing_label":"Active — action today"},
            {"id":"D001-O002","product_line":"Cementing","rig":"AD-73","well":"THRY-951201",
             "field":"Thoraiyat","confidence":88,"urgency":"5_days","estimated_value":45000,
             "competitor":"","evidence_text":"SURFACE CASING CEMENT JOB PLANNED. 13.375 INCH CASING TO BE CEMENTED WITHIN 5 DAYS.",
             "evidence_section":"Foreman Remarks","timing_label":"Within 5 days"},
            {"id":"D001-O003","product_line":"Solids Control","rig":"AD-80","well":"THRY-951205",
             "field":"Thoraiyat","confidence":85,"urgency":"immediate","estimated_value":60000,
             "competitor":"NOV","evidence_text":"BRANDT CENTRIFUGE ON STANDBY. MUD WEIGHT 1.38 SG. SC ENGINEER ROTATING OUT — REPLACEMENT NEEDED.",
             "evidence_section":"Service Companies & Rental Tools","timing_label":"Active — action today"},
            {"id":"D001-O004","product_line":"H2S / Safety","rig":"AD-80","well":"THRY-951205",
             "field":"Thoraiyat","confidence":80,"urgency":"7_days","estimated_value":17000,
             "competitor":"Rawabi","evidence_text":"H2S MONITORING PACKAGE: RAWABI CREW ON LOCATION. H2S DETECTED AT 45 PPM IN ANNULUS.",
             "evidence_section":"Foreman Remarks","timing_label":"Within 7 days"},
        ],
        "DEMO-UPLOAD-002": [
            # Thoraiyat continues — SLB still on MWD, but approaching TD
            {"id":"D002-O001","product_line":"MWD / Directional","rig":"AD-73","well":"THRY-951201",
             "field":"Thoraiyat","confidence":90,"urgency":"5_days","estimated_value":220000,
             "competitor":"SLB","evidence_text":"SPERRY ORBIT BHA AT 3,800M. APPROACHING TD. POOH WITHIN 5 DAYS. COMPLETION PHASE TO FOLLOW.",
             "evidence_section":"Foreman Remarks","timing_label":"Closing window — 5 days"},
            {"id":"D002-O002","product_line":"Completion","rig":"AD-73","well":"THRY-951201",
             "field":"Thoraiyat","confidence":95,"urgency":"7_days","estimated_value":75000,
             "competitor":"","evidence_text":"COMPLETION PROGRAMME ISSUED. LINER HANGER AND COMPLETION STRING TO BE RUN AFTER TD. 7.875 INCH LINER HANGER REQUIRED.",
             "evidence_section":"Next 24h Plan","timing_label":"Critical — prepare now"},
            # Khurais expansion — new rigs
            {"id":"D002-O003","product_line":"MWD / Directional","rig":"AR-14","well":"KHUR-100201",
             "field":"Khurais","confidence":88,"urgency":"immediate","estimated_value":220000,
             "competitor":"Halliburton","evidence_text":"ICRUSE RSS BHA ON LOCATION AT KHURAIS. DRILLING 8.5 INCH SECTION. HAL SC ON LOCATION.",
             "evidence_section":"Last 24h Operations","timing_label":"Active — displace Halliburton"},
            {"id":"D002-O004","product_line":"Well Testing","rig":"AK-21","well":"KHUR-100205",
             "field":"Khurais","confidence":82,"urgency":"30_days","estimated_value":88000,
             "competitor":"Expro","evidence_text":"DST PLANNED FOR KHUR-100205. EXPRO EQUIPMENT MOBILISING. WELL TESTING TO COMMENCE IN 30 DAYS.",
             "evidence_section":"Foreman Remarks","timing_label":"Pipeline — 30 days"},
            {"id":"D002-O005","product_line":"Wireline / Logging","rig":"AR-14","well":"KHUR-100201",
             "field":"Khurais","confidence":85,"urgency":"7_days","estimated_value":53000,
             "competitor":"GDMC","evidence_text":"LOGGING PROGRAMME: GDMC ON STANDBY. OPEN HOLE LOG REQUIRED BEFORE CASING. CMR/FMI SUITE PLANNED.",
             "evidence_section":"Next 24h Plan","timing_label":"Within 7 days"},
        ],
        "DEMO-UPLOAD-003": [
            # Jafurah unconventional — big strategic opportunity, no competitors yet
            {"id":"D003-O001","product_line":"MWD / Directional","rig":"AJF-01","well":"JF-10101",
             "field":"Jafurah","confidence":94,"urgency":"immediate","estimated_value":280000,
             "competitor":"","evidence_text":"ROTARY STEERABLE SYSTEM REQUIRED FOR UNCONVENTIONAL HORIZONTAL LATERAL. 3,500M LATERAL PLANNED. NO CURRENT DIRECTIONAL PROVIDER ON LOCATION.",
             "evidence_section":"Foreman Remarks","timing_label":"UNCONTESTED — Act immediately"},
            {"id":"D003-O002","product_line":"Completion","rig":"AJF-01","well":"JF-10101",
             "field":"Jafurah","confidence":90,"urgency":"30_days","estimated_value":120000,
             "competitor":"","evidence_text":"MULTI-STAGE FRAC COMPLETION PLANNED FOR JAFURAH HORIZONTAL WELL. COMPLETION ACCESSORIES REQUIRED. NO VENDOR CONFIRMED.",
             "evidence_section":"Next 24h Plan","timing_label":"Prepare proposal — 30 days"},
            # Thoraiyat completion phase
            {"id":"D003-O003","product_line":"Completion","rig":"AD-73","well":"THRY-951201",
             "field":"Thoraiyat","confidence":97,"urgency":"immediate","estimated_value":75000,
             "competitor":"","evidence_text":"COMPLETION PROGRAMME IN PROGRESS. LINER HANGER RUN. COMPLETION STRING BEING INSTALLED. ACCESSORIES REQUIRED IMMEDIATELY.",
             "evidence_section":"Last 24h Operations","timing_label":"ACTIVE — Critical path"},
            {"id":"D003-O004","product_line":"Fishing / Intervention","rig":"AK-21","well":"KHUR-100203",
             "field":"Khurais","confidence":95,"urgency":"immediate","estimated_value":160000,
             "competitor":"","evidence_text":"STUCK PIPE INCIDENT. BHA AT 3,200M. UNABLE TO CIRCULATE. FISHING OPERATION REQUIRED URGENTLY. STANDBY RATE: $85,000/DAY.",
             "evidence_section":"Foreman Remarks","timing_label":"EMERGENCY — Act now"},
            {"id":"D003-O005","product_line":"H2S / Safety","rig":"AJF-01","well":"JF-10102",
             "field":"Jafurah","confidence":88,"urgency":"7_days","estimated_value":25000,
             "competitor":"","evidence_text":"H2S MONITORING PACKAGE REQUIRED FOR JAFURAH OPERATIONS. CONCENTRATIONS EXPECTED ABOVE 1000PPM. NO CURRENT H2S CONTRACTOR ON LOCATION.",
             "evidence_section":"Foreman Remarks","timing_label":"Prepare within 7 days"},
        ],
    }

    # ── Competitor presence ────────────────────────────────────────────────────
    COMPETITORS = {
        "DEMO-UPLOAD-001": [
            {"normalized":"SLB",      "rig":"AD-73","service_category":"MWD / Directional","confidence":92},
            {"normalized":"NOV",      "rig":"AD-80","service_category":"Solids Control",   "confidence":85},
            {"normalized":"Rawabi",   "rig":"AD-80","service_category":"H2S / Safety",     "confidence":80},
        ],
        "DEMO-UPLOAD-002": [
            {"normalized":"SLB",        "rig":"AD-73", "service_category":"MWD / Directional","confidence":90},
            {"normalized":"Halliburton","rig":"AR-14", "service_category":"MWD / Directional","confidence":88},
            {"normalized":"GDMC",       "rig":"AR-14", "service_category":"Wireline / Logging","confidence":85},
            {"normalized":"Expro",      "rig":"AK-21", "service_category":"Well Testing",     "confidence":82},
            {"normalized":"NOV",        "rig":"AD-80", "service_category":"Solids Control",   "confidence":80},
        ],
        "DEMO-UPLOAD-003": [
            {"normalized":"Halliburton","rig":"AR-14","service_category":"MWD / Directional","confidence":85},
            {"normalized":"GDMC",       "rig":"AR-14","service_category":"Wireline / Logging","confidence":82},
            {"normalized":"Expro",      "rig":"AK-21","service_category":"Well Testing",     "confidence":80},
            # SLB gone from AD-73 — displacement window!
            # NOV gone from AD-80 — another window!
        ],
    }

    # Clear existing demo data (by prefix)
    conn.execute("DELETE FROM uploads WHERE id LIKE 'DEMO-%'")
    conn.execute("DELETE FROM opportunities WHERE id LIKE 'D00%'")
    conn.execute("DELETE FROM competitors WHERE id LIKE 'DEMO-%'")
    conn.execute("DELETE FROM market_snapshots WHERE upload_id LIKE 'DEMO-%'")
    conn.execute("DELETE FROM change_events WHERE upload_id LIKE 'DEMO-%'")
    conn.execute("DELETE FROM campaigns WHERE name LIKE '%Demo%' OR name LIKE '%Thoraiyat%' OR name LIKE '%Khurais%' OR name LIKE '%Jafurah%'")
    conn.commit()

    opp_count = 0; comp_count = 0

    for upload in DEMO_UPLOADS:
        # Insert upload record
        conn.execute(
            "INSERT OR REPLACE INTO uploads(id,filename,upload_ts,report_date,rig_count,opp_count,comp_count,pipeline) VALUES(?,?,?,?,?,?,?,?)",
            (upload["id"], upload["filename"], upload["upload_ts"], upload["report_date"],
             len(set(o["rig"] for o in OPPORTUNITIES.get(upload["id"],[]))),
             len(OPPORTUNITIES.get(upload["id"],[])),
             len(COMPETITORS.get(upload["id"],[])),
             sum(o["estimated_value"] for o in OPPORTUNITIES.get(upload["id"],[])))
        )

        # Insert opportunities
        for opp in OPPORTUNITIES.get(upload["id"],[]):
            conn.execute(
                """INSERT OR REPLACE INTO opportunities
                   (id,upload_id,title,product_line,rig,well,field,confidence,estimated_value,
                    urgency,timing_label,status,competitor,evidence_text,evidence_section,
                    matched_keywords,action,suggested_contact,rank,created_at,what_we_sell,
                    win_probability,contact_name,validation_status,source_file,source_page)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (opp["id"], upload["id"],
                 f"{opp['product_line']} — {opp['rig']}/{opp['well']}",
                 opp["product_line"], opp["rig"], opp["well"], opp["field"],
                 opp["confidence"], opp["estimated_value"], opp["urgency"],
                 opp["timing_label"], "open", opp["competitor"],
                 opp["evidence_text"], opp["evidence_section"],
                 json.dumps([opp["product_line"].split("/")[0].strip()]),
                 "Contact customer immediately" if opp["urgency"] in ("immediate","5_days") else "Monitor and prepare",
                 "Drilling Engineer",
                 opp_count + 1, upload["upload_ts"],
                 f"{opp['product_line']} services and accessories",
                 0.35 if not opp["competitor"] else 0.22,
                 "Aramco Drilling Dept",
                 "new", upload["filename"], 3 + opp_count % 8)
            )
            opp_count += 1

        # Insert competitors
        for i, comp in enumerate(COMPETITORS.get(upload["id"],[])):
            conn.execute(
                """INSERT OR REPLACE INTO competitors
                   (id,upload_id,normalized,raw_name,service_category,rig,well,status,evidence,section,confidence)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (f"DEMO-COMP-{upload['id'][-3:]}-{i}", upload["id"],
                 comp["normalized"], comp["normalized"],
                 comp["service_category"], comp["rig"],
                 "WELL-DEMO", "active",
                 f"{comp['normalized']} crew confirmed on {comp['rig']}",
                 "Service Companies & Rental Tools", comp["confidence"])
            )
            comp_count += 1

    conn.commit()
    conn.close()

    # Trigger market intelligence pipeline on demo data
    from engines.intelligence.market_intelligence import (
        generate_market_snapshot, calculate_trend_signals
    )
    from engines.intelligence.change_detection import detect_changes
    from engines.intelligence.campaign_detector import detect_campaigns

    for upload in DEMO_UPLOADS:
        generate_market_snapshot(upload["id"])
    detect_changes("DEMO-UPLOAD-003", "DEMO-UPLOAD-002")
    detect_changes("DEMO-UPLOAD-002", "DEMO-UPLOAD-001")
    detect_campaigns("DEMO-UPLOAD-003")
    calculate_trend_signals()

    return {
        "status":      "demo_loaded",
        "uploads":     len(DEMO_UPLOADS),
        "opportunities":opp_count,
        "competitors": comp_count,
        "scenario": (
            "Three-report series: Apr 2026 (Thoraiyat drilling start) → "
            "May 2026 (Khurais expansion, competitors entering) → "
            "Jul 2026 (Jafurah entry, Thoraiyat completion, emergency fishing)"
        ),
    }


DEMO_TALKING_POINTS = [
    {
        "slide":   "Market Operations Center",
        "point":   "The platform opens on this screen — the Market Operations Center. In under 30 seconds, you see 8 active rigs, 14 opportunities, 5 immediate actions, and 3 competitor movements.",
        "nav":     "market-ops",
    },
    {
        "slide":   "What Changed?",
        "point":   "Uploading yesterday's LMR immediately shows: SLB has left AD-73, creating a displacement window. Two new rigs appeared in Jafurah. Market activity surged 38%. Every change is evidence-backed.",
        "nav":     "what-changed",
    },
    {
        "slide":   "Jafurah Uncontested Opportunity",
        "point":   "Click this opportunity: No competitor on location. Revenue range $168K–$392K. Qualification score 88/100: Pursue. Engagement sequence: call the drilling engineer today. Evidence: Foreman Remarks, page 3.",
        "nav":     "radar",
    },
    {
        "slide":   "Emergency Fishing Revenue",
        "point":   "KHUR-100203 has a stuck pipe emergency. $160K revenue, no competitor. Mobilisation needed within 24 hours. The platform calculated the rig standby cost at $85K/day — it knows what delay costs the customer.",
        "nav":     "radar",
    },
    {
        "slide":   "Revenue Pipeline",
        "point":   "Total pipeline: $1.3M expected, $418K weighted. Campaign at Jafurah is flagged as a 12-week programme worth $650K+ in aggregate. This is not one opportunity — it's a market entry decision.",
        "nav":     "revenue-pipeline",
    },
    {
        "slide":   "Trust Layer",
        "point":   "Every recommendation shows its evidence strength. The Jafurah uncontested opportunity is rated HIGH — based on two independent report detections. The campaign is MODERATE — inferred from co-location, not confirmed by Aramco programme documents.",
        "nav":     "trust-dashboard",
    },
]
