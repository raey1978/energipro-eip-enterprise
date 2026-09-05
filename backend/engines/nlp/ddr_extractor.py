"""
EnergiPro – DDR / LMR Extractor v2
Correctly handles Saudi Aramco Limited Morning Report multi-rig PDFs.
Splits on the actual header: "RIG @ WELL Limited Morning Report for DATE"
"""
import re
from dataclasses import dataclass, field as dc_field
from typing import List, Optional

@dataclass
class DDRSection:
    name: str
    text: str

@dataclass
class ExtractedDDR:
    report_date: str = ""
    rig: str = ""
    well: str = ""
    field: str = ""
    objective: str = ""
    last_24h: str = ""
    next_24h: str = ""
    foreman_remarks: str = ""
    service_companies: str = ""
    equipment_on_location: str = ""
    next_location: str = ""
    mud_data: str = ""
    lost_time: str = ""
    raw_text: str = ""
    sections: List[DDRSection] = dc_field(default_factory=list)


# ─── Primary split pattern ────────────────────────────────────────────────────
# Matches: "088TE @ QTIF-798 Limited Morning Report for 05/14/2026"
#          "AD-71 @ HZEM-492604 Limited Morning Report for 05/14/2026"
#          "ADM-505 @ ZULF-1483 Limited Morning Report for 05/14/2026"
HEADER_SPLIT_PAT = re.compile(
    r'([A-Z0-9][A-Z0-9\-]*[0-9])\s+@\s+([A-Z]{2,5}-[0-9]{1,6}(?:[A-Z0-9]*)?)'
    r'\s+Limited Morning Report(?:\s+for\s+([0-9]{2}/[0-9]{2}/[0-9]{4}))?',
    re.IGNORECASE
)

# Validate rig names — must match known Saudi Aramco rig naming conventions
# This prevents column headers like "Objective", "LATE", "MAINTE" being treated as rigs
RIG_NAME_PAT = re.compile(
    r'^(?:'
    r'[0-9]{2,3}TE'          # 088TE, 095TE, 910TE
    r'|AD-[0-9]+'            # AD-71, AD-150
    r'|ADC-[0-9]+'           # ADC-14
    r'|ADM-[0-9]+'           # ADM-505
    r'|ADES-[0-9]+'          # ADES series
    r'|SP-[0-9]+'            # SP-101
    r'|SND-[0-9]+'           # SND-2001
    r'|SINO-[0-9]+'          # SINO series
    r'|HP-[0-9]+'            # HP-700
    r'|ARO-[0-9]+'           # ARO-2001
    r'|HWU-[0-9]+'           # HWU-3
    r'|PN-[0-9]+'            # PN-11
    r'|DPS-[0-9]+'           # DPS-4
    r'|ZPEC-[0-9]+'          # ZPEC
    r'|NGDOM-[0-9]+'         # NGDOM
    r'|SCTD-[0-9]+'          # SCTD
    r'|BCTD-[0-9]+'          # BCTD
    r'|JACK-[0-9]+'          # JACK
    r'|RTC-[0-9]+'           # RTC-1
    r'|BOR-[0-9]+'           # BOR-3
    r'|CH-[0-9]+'            # CH-1
    r'|CP-[0-9]+'            # CP-1
    r'|RPKU-[0-9]+'          # RPKU
    r')$',
    re.IGNORECASE
)

WELL_NAME_PAT = re.compile(
    r'^[A-Z]{2,5}-[0-9]{1,6}(?:[A-Z0-9]*)?$',
    re.IGNORECASE
)

# ─── Continuation-page running-header filter ──────────────────────────────────
# Each individual LMR report can itself span multiple physical pages (see
# "Saudi Aramco: Confidential Page 1 of 3" etc. in the raw text). Aramco's
# template reprints the report's own title line — the same
# "RIG @ WELL Limited Morning Report for DATE" text HEADER_SPLIT_PAT matches —
# as a running header at the top of every continuation page of that SAME
# report. Without filtering, HEADER_SPLIT_PAT treats each repeat as the start
# of a brand-new report, splitting one multi-page report into 2+ blocks and
# duplicating every opportunity/competitor detected in it. The continuation
# repeat is always immediately followed by this exact template fragment,
# which the genuine first-page header never is — used here to tell them apart.
CONTINUATION_HEADER_PAT = re.compile(
    r'^\s*D&WO\s+Morning\s+Report\s*\(\s*Service\s+Providers\s+View\s*\)\s*Copyright',
    re.IGNORECASE
)


def _is_valid_rig(name: str) -> bool:
    return bool(RIG_NAME_PAT.match(name.strip()))

def _is_valid_well(name: str) -> bool:
    return bool(WELL_NAME_PAT.match(name.strip()))


# ─── Section extraction (bounded to single rig block) ─────────────────────────

def _extract_between(text: str, start_pat: str, end_pats: List[str], max_len: int = 3000) -> str:
    """Extract text after start_pat up to first end_pat match. Bounded."""
    m = re.search(start_pat, text, re.IGNORECASE)
    if not m:
        return ""
    start = m.end()
    best_end = min(start + max_len, len(text))
    for ep in end_pats:
        em = re.search(ep, text[start:start + max_len], re.IGNORECASE)
        if em:
            best_end = min(best_end, start + em.start())
    return text[start:best_end].strip()


def _extract_sections(block: str, rig: str, well: str) -> List[DDRSection]:
    sections = []

    last_24h = _extract_between(
        block,
        r'Last\s+24\s+hr\s+(?:operations?|ops?)',
        [r'Next\s+24', r'Location\b', r'Current\s+Depth', r'Foreman\s+Remarks?', r'\f'],
        max_len=2000
    )
    if last_24h:
        sections.append(DDRSection("Last 24h Operations", last_24h))

    next_24h = _extract_between(
        block,
        r'Next\s+24\s+hr\s+(?:plan|operations?|ops?)',
        [r'Location\b', r'Current\s+Depth', r'Foreman\s+Remarks?', r'\f', r'={5,}'],
        max_len=2000
    )
    if next_24h:
        sections.append(DDRSection("Next 24h Plan", next_24h))

    foreman = _extract_between(
        block,
        r'Foreman\s+Remarks?',
        [r'={5,}SERVICE\s+COMP', r'={5,}EQUIPMENT', r'={5,}ADJACENT',
         r'={5,}RENTAL', r'={5,}JAR', r'={5,}PERSONNEL',
         r'\f'],
        max_len=4000
    )
    if foreman:
        sections.append(DDRSection("Foreman Remarks", foreman))

    svc = _extract_between(
        block,
        r'(?:SERVICE\s+COMP(?:ANY|ANIES)?(?:\s+&\s+RENTAL\s+TOOLS?)?|RENTAL\s+TOOLS?\s+ONBOARD|RENTAL\s+TOOLS?[:\s=])',
        [r'={5,}EQUIPMENT', r'={5,}ADJACENT', r'={5,}PERSONNEL', r'\f'],
        max_len=3000
    )
    if svc:
        sections.append(DDRSection("Service Companies & Rental Tools", svc))

    equip = _extract_between(
        block,
        r'EQUIPMENT\s+(?:&\s+)?SERVICES?\s+ON\s+LOC(?:ATION)?',
        [r'={5,}ADJACENT', r'={5,}PERSONNEL', r'\f'],
        max_len=2000
    )
    if equip:
        sections.append(DDRSection("Equipment on Location", equip))

    next_loc = _extract_between(
        block,
        r'Next\s+Loc(?:ation)?(?:\s+[=:\-])?',
        [r'Current\s+Depth', r'Formation', r'Summary', r'\f', r'={5,}'],
        max_len=500
    )
    # Also look for "Next Well:" in foreman remarks
    nw_inline = re.search(r'(?:Next\s+Well|Next\s+Location)[:\s]+([A-Z]{2,5}-[0-9]{1,6})', block, re.IGNORECASE)
    readiness = re.search(r'[Ll]ocation\s+[Rr]eadiness[:\s]+([0-9]+)\s*%', block, re.IGNORECASE)
    next_loc_combined = " ".join(filter(None, [
        next_loc,
        f"Next Well: {nw_inline.group(1)}" if nw_inline else "",
        f"Location Readiness: {readiness.group(1)}%" if readiness else ""
    ]))
    if next_loc_combined.strip():
        sections.append(DDRSection("Next Location", next_loc_combined.strip()))

    return sections


def parse_ddr_block(text: str, rig: str = "", well: str = "", date: str = "") -> ExtractedDDR:
    ddr = ExtractedDDR()
    ddr.raw_text = text
    ddr.rig = rig
    ddr.well = well
    ddr.report_date = date

    # Extract objective from header area
    obj_m = re.search(r'Objective\s*:\s*\((.+?)\)', text[:2000], re.IGNORECASE | re.DOTALL)
    if obj_m:
        ddr.objective = obj_m.group(1).strip()[:200]

    # Extract field from location or header
    field_m = re.search(r'(?:Field|Area)\s*[:\s]+([A-Za-z\s]+?)(?:\n|$)', text[:3000], re.IGNORECASE)
    if field_m:
        candidate = field_m.group(1).strip()
        if 2 < len(candidate) < 40 and not re.search(r'\d', candidate):
            ddr.field = candidate

    # Guess field from well prefix
    if not ddr.field and well:
        PREFIX_FIELDS = {
            'QTIF': 'Qatif', 'MNIF': 'Manifa', 'DMMM': 'Dammam',
            'ABSF': 'Abu Safah', 'HRDH': 'Haradh', 'SFNY': 'Safaniyah',
            'MRJN': 'Marjan', 'UTMN': 'Uthmaniyah', 'ZULF': 'Zuluf',
            'HZEM': 'Hazmiyah', 'THRY': 'Thoraiyat', 'JNAB': 'Janab',
            'KHRS': 'Khurais', 'ABHD': 'Abqaiq', 'SDGM': 'Shedgum',
            'HWYH': 'Hawiyah', 'BRRI': 'Berri', 'TINT': 'Tintamar',
            'MHWZ': 'Mahawiz', 'SDON': 'Shaybah', 'FRAS': 'Faras',
        }
        for prefix, field_name in PREFIX_FIELDS.items():
            if well.upper().startswith(prefix):
                ddr.field = field_name
                break

    ddr.sections = _extract_sections(text, rig, well)

    # Populate flat fields from sections for backward compatibility
    for sec in ddr.sections:
        if sec.name == "Last 24h Operations":     ddr.last_24h = sec.text
        elif sec.name == "Next 24h Plan":          ddr.next_24h = sec.text
        elif sec.name == "Foreman Remarks":        ddr.foreman_remarks = sec.text
        elif sec.name == "Service Companies & Rental Tools": ddr.service_companies = sec.text
        elif sec.name == "Equipment on Location":  ddr.equipment_on_location = sec.text
        elif sec.name == "Next Location":          ddr.next_location = sec.text

    return ddr


def parse_pdf_text(full_text: str) -> List[ExtractedDDR]:
    """
    Split a multi-rig LMR PDF into individual rig blocks.
    Returns one ExtractedDDR per rig.
    """
    results = []
    # Find all header positions
    headers = list(HEADER_SPLIT_PAT.finditer(full_text))

    if not headers:
        # No recognizable headers — try as single block
        ddr = parse_ddr_block(full_text)
        return [ddr] if (ddr.last_24h or ddr.foreman_remarks) else []

    # Drop continuation-page running-header repeats (see
    # CONTINUATION_HEADER_PAT above) — these are NOT new reports, just the
    # same report's title reprinted on page 2/3/... of itself.
    headers = [
        m for m in headers
        if not CONTINUATION_HEADER_PAT.match(full_text[m.end(): m.end() + 80])
    ]

    for i, match in enumerate(headers):
        rig_name  = match.group(1).strip().upper()
        well_name = match.group(2).strip().upper()
        date      = match.group(3) or ""

        # Validate rig and well names
        if not _is_valid_rig(rig_name):
            continue
        if not _is_valid_well(well_name):
            continue

        # Block ends at next header (or EOF)
        block_start = match.start()
        block_end   = headers[i + 1].start() if i + 1 < len(headers) else len(full_text)
        block_text  = full_text[block_start:block_end]

        ddr = parse_ddr_block(block_text, rig=rig_name, well=well_name, date=date)
        results.append(ddr)

    return results
