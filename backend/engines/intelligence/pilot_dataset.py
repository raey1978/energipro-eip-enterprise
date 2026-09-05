"""
EIP v6.3B — Realistic 90-Day Pilot Dataset

Creates a controlled historical dataset that tests the platform's ability to distinguish:
  - real state changes from repeated unchanged activity
  - genuine competitor entry/exit vs noise
  - sustained trends from temporary spikes
  - campaign patterns from unrelated co-located activity
  - false positives deliberately seeded

Dataset: 8 weeks across 3 phases, 4 operators, 8 rigs, 5 fields
Week 1-3:  Thoraiyat drilling campaign starts; SLB on MWD; Halliburton on completions
Week 4-5:  Khurais expansion; NESR enters; SLB exits Thoraiyat (displacement window)
Week 6-7:  Jafurah unconventional entry; emergency fishing; demand surge
Week 8:    Completion/TD phase; campaign winding down; testing begins

Deliberately seeded issues:
  - Rig AD-73 appears every week (stable — should NOT fire repeated "new rig" events)
  - AR-99 appears once then vanishes (temporary signal — should be flagged)
  - "Completion demand surge" in week 3 is real; week 4 is a false positive (same rig double-reported)
  - GDMC appears weeks 4-5 then disappears (genuine exit)
  - MWD demand trend is genuine (weeks 1→8)
  - "Well Testing surge" in week 7 is a one-off campaign, not a sustained trend
"""
import uuid, datetime, json
from core.database import get_db


SCENARIO = [
    # (week, rig, well, field, product_line, urgency, confidence, competitor, evidence, state_hint)
    # === WEEK 1: Thoraiyat drilling campaign starts ===
    ("2026-04-07","AD-73","THRY-9512","Thoraiyat","MWD / Directional","immediate",92,"SLB",
     "SPERRY ORBIT RSS BHA ON LOCATION. DRILLING 8.5IN SECTION AT 3,420M.","drilling"),
    ("2026-04-07","AD-80","THRY-9513","Thoraiyat","Cementing","5_days",85,"",
     "14IN SURFACE CASING CEMENT JOB PLANNED NEXT 5 DAYS.","drilling"),
    ("2026-04-07","AD-91","THRY-9514","Thoraiyat","Solids Control","immediate",80,"NOV",
     "BRANDT CENTRIFUGE ON LOCATION. MUD WEIGHT 1.38SG.","drilling"),

    # === WEEK 2: Same rigs, same states (should NOT generate repeated change events) ===
    ("2026-04-14","AD-73","THRY-9512","Thoraiyat","MWD / Directional","immediate",91,"SLB",
     "SPERRY ORBIT RSS BHA CONTINUING. DRILLING AHEAD AT 3,820M. ROP 14M/HR.","drilling"),
    ("2026-04-14","AD-80","THRY-9513","Thoraiyat","Cementing","7_days",82,"",
     "CEMENT SLURRY DESIGN COMPLETE. JOB PLANNED NEXT WEEK.","drilling"),
    ("2026-04-14","AD-91","THRY-9514","Thoraiyat","Solids Control","immediate",78,"NOV",
     "CENTRIFUGE RUNNING CONTINUOUSLY. SOLIDS CONTROL ENGINEER ON LOCATION.","drilling"),
    # FALSE POSITIVE SEED: AR-99 appears only this week (temporary ghost signal)
    ("2026-04-14","AR-99","GHOST-001","Thoraiyat","Rental / Intervention","future",55,"",
     "RENTAL TOOL STANDBY. NOT YET MOBILISED.","standby"),

    # === WEEK 3: Completion on AD-73 — genuine state transition ===
    ("2026-04-21","AD-73","THRY-9512","Thoraiyat","Completion","immediate",95,"",
     "TD REACHED. LINER HANGER AND COMPLETION STRING RUNNING. NO CURRENT COMPLETION VENDOR.",
     "completion"),  # STATE CHANGE: drilling → completion
    ("2026-04-21","AD-80","THRY-9513","Thoraiyat","Cementing","immediate",88,"",
     "CEMENT JOB IN PROGRESS. 13.375IN CASING CEMENTED TO 2,850M.","cementing"),
    ("2026-04-21","AD-91","THRY-9514","Thoraiyat","Solids Control","immediate",80,"NOV",
     "CENTRIFUGE RUNNING. BUILDING ANOTHER HOLE SECTION.","drilling"),
    # FALSE POSITIVE SEED: Same AD-73 completion reported again (duplicate DDR page)
    ("2026-04-21","AD-73","THRY-9512","Thoraiyat","Completion","immediate",93,"",
     "LINER HANGER RUNNING — COMPLETION IN PROGRESS. [DUPLICATE REPORT PAGE]","completion"),

    # === WEEK 4: Khurais expansion — SLB exits Thoraiyat, NESR enters ===
    ("2026-04-28","AR-14","KHUR-1002","Khurais","MWD / Directional","immediate",90,"Halliburton",
     "ICRUSE RSS BHA ON LOCATION AT KHURAIS. DRILLING 8.5IN.","drilling"),
    ("2026-04-28","AK-21","KHUR-1005","Khurais","Well Testing","30_days",78,"Expro",
     "DST PLANNED FOR KHUR-1005. EXPRO EQUIPMENT MOBILISING. 30 DAYS.","planned"),
    ("2026-04-28","AD-73","THRY-9515","Thoraiyat","MWD / Directional","immediate",88,"NESR",
     "NESR DIRECTIONAL CREW ON LOCATION. NEW WELL THRY-9515 SPUDDED.",
     "drilling"),  # NEW WELL — NESR replaced SLB (competitor change)
    ("2026-04-28","GDMC-RIG-1","KHUR-1007","Khurais","Wireline / Logging","7_days",82,"GDMC",
     "GDMC WIRELINE UNIT ON LOCATION. OPEN HOLE LOGGING PLANNED.","drilling"),

    # === WEEK 5: Khurais expanding, GDMC confirmed ===
    ("2026-05-05","AR-14","KHUR-1002","Khurais","MWD / Directional","immediate",89,"Halliburton",
     "DRILLING AHEAD 3,950M. APPROACHING TD. HALLIBURTON DIRECTIONAL.","drilling"),
    ("2026-05-05","AR-56","KHUR-1009","Khurais","Cementing","5_days",84,"",
     "NEW RIG AR-56 SPUDDED AT KHURAIS. SURFACE CASING CEMENT REQUIRED.","drilling"),
    ("2026-05-05","AD-73","THRY-9515","Thoraiyat","MWD / Directional","immediate",87,"NESR",
     "NESR ON LOCATION THRY-9515. DRILLING 8.5IN AT 2,100M.","drilling"),
    ("2026-05-05","GDMC-RIG-1","KHUR-1007","Khurais","Wireline / Logging","immediate",83,"GDMC",
     "GDMC FMI LOG RUN COMPLETE. INTERPRETING RESULTS.","logging"),

    # === WEEK 6: Jafurah entry — no competitor, immediate, high value ===
    ("2026-05-12","AJF-01","JF-10101","Jafurah","MWD / Directional","immediate",94,"",
     "NEW UNCONVENTIONAL RIG AJF-01 AT JAFURAH. RSS REQUIRED FOR 3,500M LATERAL. NO VENDOR.",
     "drilling"),
    ("2026-05-12","AJF-01","JF-10102","Jafurah","H2S / Safety","7_days",88,"",
     "H2S MONITORING PACKAGE REQUIRED FOR JAFURAH OPERATIONS. EXPECTED >1000PPM. NO CONTRACTOR.",
     "drilling"),
    ("2026-05-12","AK-21","KHUR-1005","Khurais","Well Testing","immediate",88,"Expro",
     "DST COMMENCED ON KHUR-1005. EXPRO SEPARATOR ON LOCATION.","testing"),
    # GDMC exits — last appearance was week 5
    ("2026-05-12","AR-14","KHUR-1002","Khurais","Fishing / Intervention","immediate",95,"",
     "STUCK PIPE ON AR-14. BHA AT 4,100M. EMERGENCY FISHING REQUIRED. STANDBY RATE $85K/DAY.",
     "intervention"),  # STATE CHANGE: drilling → intervention

    # === WEEK 7: Jafurah growing, completion elsewhere ===
    ("2026-05-19","AJF-01","JF-10101","Jafurah","MWD / Directional","immediate",93,"",
     "DRILLING LATERAL. 1,200M INTO LATERAL SECTION. STILL NO DIRECTIONAL VENDOR ON LOCATION.",
     "drilling"),
    ("2026-05-19","AJF-02","JF-10201","Jafurah","MWD / Directional","immediate",90,"",
     "NEW RIG AJF-02 SPUDDED AT JAFURAH. SECOND UNCONVENTIONAL WELL. NO DIRECTIONAL VENDOR.",
     "drilling"),  # CAMPAIGN: Jafurah now 2 rigs = campaign confirmed
    ("2026-05-19","AD-73","THRY-9515","Thoraiyat","Completion","immediate",92,"",
     "THRY-9515 APPROACHING TD. COMPLETION PROGRAMME ISSUED. NO COMPLETION VENDOR.",
     "completion"),  # STATE CHANGE: drilling → completion
    # ONE-OFF SPIKE: Well Testing demand — weeks 6+7 only, not a sustained trend
    ("2026-05-19","AR-56","KHUR-1009","Khurais","Well Testing","30_days",76,"",
     "KHUR-1009 PLANNING DST. TEST PROGRAMME BEING PREPARED.","planned"),

    # === WEEK 8: Campaign winding down, testing peaks ===
    ("2026-05-26","AJF-01","JF-10101","Jafurah","MWD / Directional","immediate",91,"",
     "LATERAL DRILLING COMPLETE. APPROACHING TOTAL DEPTH. TD NEXT 5 DAYS.","drilling"),
    ("2026-05-26","AJF-02","JF-10201","Jafurah","MWD / Directional","immediate",89,"",
     "AJF-02 DRILLING 8.5IN SECTION. LATERAL AT 800M. STILL NO DIRECTIONAL VENDOR.","drilling"),
    ("2026-05-26","AK-21","KHUR-1005","Khurais","Well Testing","immediate",90,"Expro",
     "DST ONGOING. EXCELLENT FLOW RATES. EXTENDING TEST PERIOD.","testing"),
    ("2026-05-26","AD-80","THRY-9513","Thoraiyat","Solids Control","immediate",77,"",
     "AD-80 SPUDDING NEW WELL THRY-9516. CENTRIFUGE REQUIRED.","drilling"),
    # GDMC gone — confirmed exit
]


def seed_pilot_dataset() -> dict:
    """Seed the 90-day pilot dataset. Returns summary."""
    from engines.intelligence.entity_resolution import process_upload_entities
    from engines.intelligence.market_intelligence import generate_market_snapshot
    from engines.intelligence.change_detection import detect_changes
    from engines.intelligence.campaign_detector import detect_campaigns
    from engines.intelligence.trust_layer import calculate_trust_envelope, store_trust_score

    conn = get_db()

    # Group by week → creates one upload per week
    weeks = {}
    for row in SCENARIO:
        (rdate, rig, well, field, pl, urg, conf, comp, ev, state) = row
        week_key = rdate[:10]
        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(row)

    # Clear existing pilot data
    conn.execute("DELETE FROM uploads WHERE id LIKE 'PILOT-%'")
    conn.execute("DELETE FROM opportunities WHERE id LIKE 'PILOT-%'")
    conn.execute("DELETE FROM competitors WHERE id LIKE 'PILOT-%'")
    conn.commit()

    upload_ids = []
    total_opps = 0
    total_comps = 0

    for rdate, rows in sorted(weeks.items()):
        uid = f"PILOT-{rdate}"
        upload_ids.append(uid)
        conn.execute(
            "INSERT OR REPLACE INTO uploads(id,filename,upload_ts,report_date,rig_count,opp_count,comp_count,pipeline) VALUES(?,?,?,?,?,?,?,?)",
            (uid, f"LMR_{rdate}.pdf", f"{rdate}T06:00:00",
             rdate, len(set(r[1] for r in rows)),
             len(rows), sum(1 for r in rows if r[7]), len(rows)*150000)
        )

        seen = set()
        for i, (rdate2,rig,well,field,pl,urg,conf,comp,ev,state) in enumerate(rows):
            oid = f"PILOT-{rdate}-{i:02d}"
            conn.execute(
                """INSERT OR REPLACE INTO opportunities
                   (id,upload_id,title,product_line,rig,well,field,confidence,estimated_value,
                    urgency,competitor,evidence_text,evidence_section,matched_keywords,
                    contact_name,what_we_sell,rank,created_at,source_file,source_page,validation_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (oid, uid, f"{pl} — {rig}/{well}", pl, rig, well, field, conf,
                 {"MWD / Directional":220000,"Completion":75000,"Cementing":45000,
                  "Solids Control":60000,"Well Testing":88000,"Fishing / Intervention":160000,
                  "H2S / Safety":25000,"Wireline / Logging":53000,"Rental / Intervention":22000
                 }.get(pl,50000),
                 urg, comp, ev, "Foreman Remarks",
                 json.dumps([pl.split("/")[0].strip()]),
                 "Aramco Drilling Dept", pl, i+1,
                 f"{rdate}T06:00:00", f"LMR_{rdate}.pdf", i+3, "new")
            )
            total_opps += 1

            if comp and (comp, rig) not in seen:
                seen.add((comp, rig))
                conn.execute(
                    "INSERT OR REPLACE INTO competitors(id,upload_id,normalized,raw_name,rig,service_category,well,status,evidence,section,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (f"PILOT-comp-{rdate}-{i}", uid, comp, comp, rig, pl, well,
                     "active", f"{comp} crew on {rig}", "Service Companies & Rental Tools", conf)
                )
                total_comps += 1

    conn.commit()

    # Run intelligence pipeline per upload
    prev_uid = None
    for uid in upload_ids:
        rdate = uid.replace("PILOT-","")
        process_upload_entities(uid, rdate)
        generate_market_snapshot(uid)
        if prev_uid:
            detect_changes(uid, prev_uid)
        detect_campaigns(uid)
        prev_uid = uid

    conn.close()

    return {
        "status":         "pilot_dataset_loaded",
        "weeks":          len(weeks),
        "upload_ids":     upload_ids,
        "total_opps":     total_opps,
        "total_comps":    total_comps,
        "rigs":           list(set(r[1] for r in SCENARIO)),
        "fields":         list(set(r[3] for r in SCENARIO)),
        "deliberately_seeded_issues": [
            "AR-99: Temporary ghost signal (appears week 2 only)",
            "AD-73 duplicate completion record in week 3 (same page reported twice)",
            "GDMC exits after week 5 — genuine competitor withdrawal",
            "Well Testing spike weeks 6-7 — one-off campaign, NOT a sustained trend",
            "MWD demand weeks 1-8 — genuine sustained growth (Jafurah adds 2 rigs)",
            "SLB exits Thoraiyat week 4 — displacement window opens",
            "Jafurah campaign: 1 rig week 6 → 2 rigs week 7 — campaign confirmed",
        ],
        "expected_detections": {
            "state_transitions": [
                "AD-73 THRY-9512: drilling → completion (week 3)",
                "AD-73 THRY-9515: drilling → completion (week 7)",
                "AR-14 KHUR-1002: drilling → intervention (week 6)",
            ],
            "competitor_movements": [
                "SLB exits Thoraiyat (week 3→4)",
                "NESR enters Thoraiyat (week 4)",
                "GDMC exits Khurais (week 6→7)",
                "Halliburton enters Khurais (week 4)",
            ],
            "campaigns": [
                "Thoraiyat drilling campaign (weeks 1-7, 3 rigs)",
                "Khurais expansion (weeks 4-7, 3 rigs)",
                "Jafurah unconventional (weeks 6-8, 2 rigs)",
            ],
            "trends": [
                "MWD/Directional: growing (weeks 1→8, 4→6 concurrent opportunities)",
                "Completion: spike week 3-4 only (should be Short-Term Spike, not Sustained)",
                "Well Testing: one-off (weeks 6-7 only)",
            ],
        },
    }
