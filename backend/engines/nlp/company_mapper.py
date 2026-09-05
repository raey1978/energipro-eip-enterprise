"""
EnergiPro – Competitor Detection & Normalization Engine v3.2
Full Saudi Aramco SC_Abbreviations database (387 entries) + tool brand aliases.
"""
import re
from dataclasses import dataclass
from typing import List

@dataclass
class CompetitorMention:
    normalized: str
    raw_name: str
    service_category: str
    rig: str
    well: str
    status: str      # on_location | released | planned | mentioned
    evidence: str
    section: str
    confidence: int = 80


# ── Helper: build category from service description ───────────────────────────
def _cat(svc_desc: str) -> str:
    d = svc_desc.upper()
    # Order matters — more specific first
    if any(x in d for x in ['DIRECTIONAL','MWD','LWD','MEASUREMENT WHILE','RSS BHA','GYRO','MUD LOGGING','REAL TIME DATA']): return 'MWD / Directional'
    if any(x in d for x in ['CEMENTING','CEMENT JOB','CEMENT SERV','CEMENT ACCESS','PRIMARY CEMENT','LINER CEMENT','SQUEEZE CEMENT']): return 'Cementing'
    if any(x in d for x in ['FISHING','WHIPSTOCK','MILLING WINDOW','WELLBORE CLEAN','SLOT RECOV','THROUGH TUBING']): return 'Fishing / Intervention'
    if any(x in d for x in ['WIRELINE','SLICK LINE','SLICKLINE','WIRE LINE LOG','WIRELINE LOG','PERFORATION']): return 'Wireline / Logging'
    if any(x in d for x in ['COIL TUBING','COILED TUBING','STIMULAT','ACIDIZ','FRACTUR']): return 'Rental / Intervention'
    if any(x in d for x in ['COMPLETION','LINER HANGER','BRIDGE PLUG','TUBULAR RUN','CASING RUN','CASING/TUBING','EXPANDABLE']): return 'Completion'
    if any(x in d for x in ['H2S DETECT','H2S MONITOR','H2S SAFETY','SAFETY PACKAGE']): return 'H2S / Safety'
    if any(x in d for x in ['SOLID CONTROL','SHAKER','CENTRIFUGE','WASTE MGMT','WASTE MANAGEMENT','BARITE RECOV']): return 'Solids Control'
    if any(x in d for x in ['DRILLING FLUID','MUD ENGINEER','MUD FLUID','FILTRATION SERV','BAROID']): return 'Solids Control'
    if any(x in d for x in ['WELL TEST','WELL FLOW','FLOWBACK','DST']): return 'Well Testing'
    if any(x in d for x in ['RENTAL TOOL','JARS','SHOCK TOOL','DOWNHOLE TOOL','DRILL BIT']): return 'Rental / Intervention'
    return 'Oilfield Services'


# ── Parent abbreviation → display name ───────────────────────────────────────
_PARENT_DISPLAY = {
    'SCH': 'SLB',
    'BHG': 'Baker Hughes',
    'HAL': 'Halliburton',
    'WFD': 'Weatherford',
    'NOV': 'NOV',
    'NER': 'NESR',
    'NPP': 'NAPESCO',
    'MSO': 'AlMansoori',
    'ZG':  'Oilserv (Zamil)',
    'SJL': 'TAQA Group',
    'EXP': 'Expro',
    'RTR': 'Rawabi Trading',
    'ROG': 'Rawabi O&G',
    'RUE': 'Rawabi United',
    'GU':  'Gulf Energy',
    'SS':  'Sinopec',
    'FRK': 'Franks',
    'GDM': 'GDMC',
    'SAM': 'Samaa',
    'CRT': 'Coretrax',
    'NAB': 'Nabors',
    'MBP': 'Mohamed Barwani',
    'SPC': 'Sapesco',
    'WDC': 'Well Dynamic Energy',
    'WIS': 'WIS (Wellbore Integrity)',
    'INN': 'Innovex',
    'TTR': 'Tetra',
    'NPS': 'NESR',
    'GT1': 'Gas & Oil Technologies',
    'SG0': 'SGS',
    'SCD': 'Scientific Drilling',
    'PII': 'PI-Intervention',
    'DEC': 'Dynamic Energy',
    'SW':  'Sawafi Group',
    'AEF': 'Arabian Est. Fishing',
    'SIE': 'Synergy Energy',
    'ASO': 'Albinail Sprint',
    'JEC': 'Jereh Energy',
    'TIW': 'TIW',
    'INW': 'Interwell',
    'ULT': 'Ulterra',
    'VAR': 'Varel',
    'KSC': 'Khorayef Sons',
    'RXR': 'Roxar',
    'AOS': 'AZR Petroleum',
    'CPR': 'Corpro',
    'KOT': 'KMC Oil Tools',
    'PMD': 'Primadrill',
    'NES': 'Nesma',
    'PCS': 'Rezayat',
    'ITS': 'International Tubular',
    'DMT': 'Diamant',
    'DRF': 'Drillformance',
    'WFL': 'Well Flow',
    'SMT': 'Summit Technologies',
    'PWS': 'Power Well Services',
    'TSF': 'Total Safety',
    'WCC': 'Wellcem',
    'ANT': 'Antech',
    'BGP': 'Bureau Geophysical',
    'GCD': 'Gyrodata',
    'XLG': 'Exlog',
}

_SKIP_PARENTS = {
    'SAUDI ARAMCO', 'SAUDI ARAMCO - NON D &WO', 'RIG', 'OTHER OR UNKNOWN',
    'NATIVE SAUDI', 'NATIONAL FACTORY', ''
}
_SKIP_ABBREVS = {'RIG', 'OTH', 'N', 'NF', 'ARM', 'ARN', 'AMA', 'APR', 'AP1', 'AP2', 'APF', 'MRN', 'TLH', 'SNG', 'A20', 'AM1', 'AM', 'KAF', 'RZT', 'SCC', 'SWK', 'NCM', 'RSI', 'SSR', 'GSC'}


def _build_abbrev_map():
    """
    Build the abbreviation lookup from the embedded SC_Abbreviations data.
    Returns: dict of  ABBREV → (display_name, category)
    """
    # Raw data extracted from SC_Abbreviations.xlsx
    # Format: (svc_abbr, svc_desc, par_abbr, par_name)
    RAW = [
        ('ALC','ARTIFICIAL LIFT COMPANY','ALC','ARTIFICIAL LIFT COMPANY'),
        ('BAL','BAKER HUGHES ARTIFICIAL LIFT','BHG','BAKER HUGHES'),
        ('KSC','KHORAYEF SONS COMPANY','KSC','KHORAYEF SONS COMPANY'),
        ('RXR','ROXAR','RXR','ROXAR'),
        ('SBA','SAWAFI BORETS ARTIFICIAL LIFT','SW','SAWAFI GROUP'),
        ('SWA','SCHLUMBERGER WELL ARTIFICIAL','SCH','SCHLUMBERGER'),
        ('WAL','WEATHERFORD ARTIFICIAL LIFT','WFD','WEATHERFORD'),
        ('BHT','BAKER HUGHES DRILL BITS','BHG','BAKER HUGHES'),
        ('CDB','CHENGDU BEST DIAMOND BIT CO','CDB','CHENGDU BEST DIAMOND BIT CO'),
        ('DMT','DIAMANT','DMT','DIAMANT'),
        ('DRF','DRILLFORMANCE','DRF','DRILLFORMANCE'),
        ('RTC','REED/HYCALOG','NOV','NATIONAL OILWELL VARCO'),
        ('SBT','SMITH BITS','SCH','SCHLUMBERGER'),
        ('SEC','SECURITY-DBS','HAL','HALLIBURTON'),
        ('ULT','ULTERRA','ULT','ULTERRA'),
        ('VAR','VAREL','VAR','VAREL'),
        ('AOS','AZR PETROLEUM COMPANY','AOS','AZR PETROLEUM COMPANY'),
        ('AZ1','TAQA WIRELINE (AZR)','SJL','TAQA GROUP'),
        ('BAW','BAKER HUGHES WIRELINE SERVICES','BHG','BAKER HUGHES'),
        ('BC1','BAKER BRIDGE PLUG AND RETAINER','BHG','BAKER HUGHES'),
        ('BCM','BAKER HUGHES CEMENTING SERVICE','BHG','BAKER HUGHES'),
        ('BFW','BAKER FISHING SERVICE','BHG','BAKER HUGHES'),
        ('HCB','HALLIBURTON BRIDGE PLUG/RETR','HAL','HALLIBURTON'),
        ('HCM','HALLIBURTON CEMENTING SERVICES','HAL','HALLIBURTON'),
        ('HCT','HALLIBURTON BOOTS & COOTS (CT)','HAL','HALLIBURTON'),
        ('HWP','HALLIBURTON W/L & PERFORATION','HAL','HALLIBURTON'),
        ('INW','INTERWELL','INW','INTERWELL'),
        ('NC1','NOV COMPLETION','NOV','NATIONAL OILWELL VARCO'),
        ('NCS','NPS CEMENTING','NER','NESR COMPANY'),
        ('PII','PI-INTERVENTION','PII','PI-INTERVENTION'),
        ('SCB','SCHL BRIDGE PLUG/RETNR','SCH','SCHLUMBERGER'),
        ('SCM','SCHL. WELL SERVICES CEMENTING','SCH','SCHLUMBERGER'),
        ('SJC','SANJEL CEMENTING','SJL','TAQA GROUP'),
        ('SWL','SCHLUMBERGER WIRELINE','SCH','SCHLUMBERGER'),
        ('WBP','WFD BRIDGE PLUGS AND RETAINERS','WFD','WEATHERFORD'),
        ('WCT','WEATHERFORD COIL TUBING','WFD','WEATHERFORD'),
        ('WWL','WFD WIRE LINE LOGGING SERVICES','WFD','WEATHERFORD'),
        ('BCS','BAKER HUGHES CORING SERVICES','BHG','BAKER HUGHES'),
        ('HCS','HALLIBURTON CORING SERVICES','HAL','HALLIBURTON'),
        ('NOC','NOV CORING SERVICE','NOV','NATIONAL OILWELL VARCO'),
        ('WRT','WEATHERFORD RENTAL SERVICES','WFD','WEATHERFORD'),
        ('AS1','ALBINAIL SPRINT OG COIL TUBING','ASO','ALBINAIL SPRINT'),
        ('BCT','BAKER HUGHES COIL TUBING SERV.','BHG','BAKER HUGHES'),
        ('BHO','BKR HGH CTD INTEGRATED OPERAT.','BHG','BAKER HUGHES'),
        ('BTT','BAKER HUGHES THROUGH TUBING','BHG','BAKER HUGHES'),
        ('CJE','C &J ENERGY SERVICES','WDC','WELL DYNAMIC ENERGY'),
        ('GD2','GDM COIL TUBING','GDM','GULF DRILLING AND MAINTENANCE'),
        ('JCT','JEREH ENERGY COILED TUBING','JEC','JEREH ENERGY'),
        ('MCT','MANSOORI COIL TUBING','MSO','MANSOORI OILFIELD SERVICES'),
        ('NCT','NPS COIL TUBING','NER','NESR COMPANY'),
        ('OZT','OILSERV COILTUBING (ZAMIL)','ZG','ZAMIL GROUP'),
        ('SC1','SINOPEC COIL TUBING','SS','SINOPEC SERVICES'),
        ('SCT','SCHL WELL SERVICES COIL TUBING','SCH','SCHLUMBERGER'),
        ('SJT','SANJEL COIL TUBING','SJL','TAQA GROUP'),
        ('STT','SMITH THROUGH TUBING','SCH','SCHLUMBERGER'),
        ('WTS','WFD THROUGH TUBING SERVICES','WFD','WEATHERFORD'),
        ('BCI','BAROID CUTTING INJECTION','HAL','HALLIBURTON'),
        ('BR2','BRAND WASTE MANAGEMENT','NOV','NATIONAL OILWELL VARCO'),
        ('BWS','BAKER WASTE MANAGEMENT','BHG','BAKER HUGHES'),
        ('GZC','GULF ENERGY CUTTING MGMT','GU','GULF ENERGY'),
        ('KOT','KMC OIL TOOLS','KOT','KMC OIL TOOLS'),
        ('MI3','SCH MI WASTE MANAGEMENT SVC','SCH','SCHLUMBERGER'),
        ('NCA','NOV CEMENTING ACCESSORIES','NOV','NATIONAL OILWELL VARCO'),
        ('AM2','AMCO RUNNING CASING','AMM','AMCO'),
        ('BCR','BKR HGHS TUBULAR RUNNING SERV','BHG','BAKER HUGHES'),
        ('CAM','CAMERON IRON WORKS','SCH','SCHLUMBERGER'),
        ('FMC','FRANKS AND TAMIMI','FRK','FRANKS'),
        ('ITS','INTERNATIONAL TUBULAR SERVC','ITS','INTERNATIONAL TUBULAR SERVC'),
        ('MCR','MANSOORI CASING/TUBING RUNNING','MSO','MANSOORI OILFIELD SERVICES'),
        ('PM1','PRIMADRILL RUNNING CASING','PMD','PRIMADRILL'),
        ('RUE','RAWABI UNITED ENTERPRISES','RUE','RAWABI UNITED ENTERPRISES'),
        ('SLC','SCHLUMBERGER CASING DRILLING','SCH','SCHLUMBERGER'),
        ('SPR','SAPESCO CASING/TUBING RUNNING','NER','NESR COMPANY'),
        ('TSC','TESCO CORPORATION','TSC','TESCO CORPORATION'),
        ('TTR','TETRA','TTR','TETRA'),
        ('WCR','WFD CASING RUNNING SERVICES','WFD','WEATHERFORD'),
        ('ZPC','PREMIERE CASING SERV (ZAMIL)','ZG','ZAMIL GROUP'),
        ('EXP','EXPRO','EXP','EXPRO'),
        ('BAR','BAROID DRILLING FLUIDS','HAL','HALLIBURTON'),
        ('BDF','BAKER HUGHES DRILLING FLUIDS','BHG','BAKER HUGHES'),
        ('EMC','EGYPTIAN MUD COMPANY','EMC','EGYPTIAN MUD COMPANY'),
        ('IDF','INTERNATIONAL DRILLING FLUIDS','IDF','INTERNATIONAL DRILLING FLUIDS'),
        ('MB1','MBP DRILLING FLUIDS','MBP','MOHAMED BARWANI PETROLEUM CO.'),
        ('MBS','MB PETROLEUM SERVICES','MBS','MB PETROLEUM SERVICES'),
        ('NW1','NEWPARK DRILLING FLUIDS','NWP','NEWPARK'),
        ('SMI','SCH MI DRILLING FLUIDS','SCH','SCHLUMBERGER'),
        ('ANT','ANTECH','ANT','ANTECH'),
        ('BHI','BKR HUGHES DIRECT DRILLING','BHG','BAKER HUGHES'),
        ('CDS','COUGAR DIRECTIONAL SERVICE','SJL','TAQA GROUP'),
        ('GTC','GAS & OIL TECH DIRECT DRILL.','GT1','GAS & OIL TECHNOLOGIES LLC'),
        ('ND1','NERS DIRECTIONAL DRILLING','NER','NESR COMPANY'),
        ('NDD','NOV DIRECTIONAL DRILLING','NOV','NATIONAL OILWELL VARCO'),
        ('NDS','NABORS DIRECTIONAL DRILLING','NAB','NABORS SERVICES'),
        ('NE1','NESMA DIRECTIONAL DRILLING','NES','NESMA'),
        ('ODD','OILSERV DIRECTIONAL DRILLING','ZG','ZAMIL GROUP'),
        ('SCD','SCIENTIFIC DRILLING','SCD','SCIENTIFIC DRILLING'),
        ('SDM','SCHL. DRILLING & MEASUREMENT','SCH','SCHLUMBERGER'),
        ('SPS','SPERRY SUN','HAL','HALLIBURTON'),
        ('WDS','WFD DIRECTIONAL DRLNG SERVICES','WFD','WEATHERFORD'),
        ('CTC','COUGAR TOOL CO','SJL','TAQA GROUP'),
        ('FRW','FRANKS RAWABI RENTAL TOOLS','FRK','FRANKS'),
        ('NPD','NAPESCO DOWNHOLE TOOLS','NPP','NAPESCO'),
        ('SAM','SAMAA TECHNOLOGIES','SAM','SAMAA TECHNOLOGIES'),
        ('SMT','SUMMIT TECHNOLOGIES','SMT','SUMMIT TECHNOLOGIES'),
        ('SNT','SINOPEC DOWNHOLE TOOLS','SS','SINOPEC SERVICES'),
        ('SRT','SMITH RENTAL TOOLS','SCH','SCHLUMBERGER'),
        ('WFL','WELL FLOW','WFL','WELL FLOW'),
        ('WWB','WEATHERFORD WELLBORE CLEANING','WFD','WEATHERFORD'),
        ('WWT','WESTERN WELL TOOL','WWT','WESTERN WELL TOOL'),
        ('BCA','BAKER HUGHES CEMENTING ACCESSORIES','BHG','BAKER HUGHES'),
        ('HCA','HALLIBURTON CEMENT ACCESSORIES','HAL','HALLIBURTON'),
        ('WCM','WEATHERFORD CEMENTING','WFD','WEATHERFORD'),
        ('HDV','HALLIBURTON DV TOOL','HAL','HALLIBURTON'),
        ('TOD','TEAM OIL TOOLS DV TOOL','INN','INNOVEX'),
        ('WDV','WEATHERFORD DV TOOL','WFD','WEATHERFORD'),
        ('BC','BAKER HUGHES COMPLETION SERV.','BHG','BAKER HUGHES'),
        ('HCO','HALLIBURTON COMPLETION TOOLS','HAL','HALLIBURTON'),
        ('SCP','SCHLUMBERGER COMPLETION','SCH','SCHLUMBERGER'),
        ('WCS','WFD COMPLETION SERVICES','WFD','WEATHERFORD'),
        ('WDC','WELL DYNAMIC ENERGY','WDC','WELL DYNAMIC ENERGY'),
        ('BFL','BAROID FILTRATION','HAL','HALLIBURTON'),
        ('BFS','BAKER HUGHES FILTRATION','BHG','BAKER HUGHES'),
        ('EXF','EXPRO FILTRATION','EXP','EXPRO'),
        ('MFT','MANSOORI FILTRATION','MSO','MANSOORI OILFIELD SERVICES'),
        ('NFT','NPS FILTRATION','NER','NESR COMPANY'),
        ('RTF','RAWABI TRADING FILTRATION','RTR','AL-RAWABI TRADING'),
        ('WFF','WEATHERFORD FILTRATION SERVICES','WFD','WEATHERFORD'),
        ('GD1','GDM SLICK LINE','GDM','GULF DRILLING AND MAINTENANCE'),
        ('MH2','MANSOORI H2S DETECTION','MSO','MANSOORI OILFIELD SERVICES'),
        ('SNS','SINOPEC H2S','SS','SINOPEC SERVICES'),
        ('TSF','TOTAL SAFETY COMPANY','TSF','TOTAL SAFETY COMPANY'),
        ('NRT','NOV RENTAL TOOLS','NOV','NATIONAL OILWELL VARCO'),
        ('GEI','GULF ENERGY INSPECTION','GU','GULF ENERGY'),
        ('MSI','MANSOORI TUBULAR INSPECTION','MSO','MANSOORI OILFIELD SERVICES'),
        ('SPI','SAPESCO TUBULAR INSPECTION','SPC','SAPESCO'),
        ('GDF','GULF ENERGY INTEGRATED SERV','GU','GULF ENERGY'),
        ('BLH','BAKER HUGHES LINER HANGER','BHG','BAKER HUGHES'),
        ('HLH','HALLIBURTON LINER HANGER','HAL','HALLIBURTON'),
        ('SLH','SMITH LINER HANGER','SCH','SCHLUMBERGER'),
        ('TOT','TEAM OIL TOOLS LINER HANGER','INN','INNOVEX'),
        ('WLH','WFD LINER HANGER SERVICES','WFD','WEATHERFORD'),
        ('AZ2','AZR SLICK LINE','SJL','TAQA GROUP'),
        ('BGP','BUREAU GEOPHYSICAL PROSPECT','BGP','BUREAU GEOPHYSICAL PROSPECT'),
        ('NWL','NPS WIRELINE','NER','NESR COMPANY'),
        ('OWL','OILSERV WIRELINE (ZAMIL)','ZG','ZAMIL GROUP'),
        ('SWG','SCHLUMBERGER WESTERN GECO','SCH','SCHLUMBERGER'),
        ('HMS','HALLIBURTON MUD LOGGING AND RT','HAL','HALLIBURTON'),
        ('RO1','RAWABI O&G GEOLOGY','ROG','RAWABI OIL & GAS'),
        ('WML','WEATHERFORD MUD LOGGING','WFD','WEATHERFORD'),
        ('BSC','BAROID SOLID CONTROL SVC','HAL','HALLIBURTON'),
        ('BSS','BAKER SOLID CONTROL','BHG','BAKER HUGHES'),
        ('BRD','BRANDT SOLID CONTROL','NOV','NATIONAL OILWELL VARCO'),
        ('GU1','GULF ENERGY SOLID CONTROL','GU','GULF ENERGY'),
        ('MI2','SCH MI SOLID CONTROL SVC','SCH','SCHLUMBERGER'),
        ('MSW','MI SWACO','SCH','SCHLUMBERGER'),
        ('BCT','BAKER HUGHES COIL TUBING SERV.','BHG','BAKER HUGHES'),
        ('NST','NPS STIMULATION','NER','NESR COMPANY'),
        ('SJA','SANJEL ACIDIZING & STIMULATION','SJL','TAQA GROUP'),
        ('SWF','SCHL. WELL SERVICES FRACTURING','SCH','SCHLUMBERGER'),
        ('HPE','HALLIBURTON PRODUCTION ENHANCE','HAL','HALLIBURTON'),
        ('NPC','NAPESCO JARS','NPP','NAPESCO'),
        ('NPJ','NPS JARS','NER','NESR COMPANY'),
        ('OJR','OILSERV JARS (ZAMIL)','ZG','ZAMIL GROUP'),
        ('SJS','SCHLUMBERGER JARS','SCH','SCHLUMBERGER'),
        ('WJS','WEATHERFORD JARS','WFD','WEATHERFORD'),
        ('AE1','ARABIAN EST. FISHING','AEF','ARABIAN EST. FISHING'),
        ('BFW','BAKER FISHING SERVICE','BHG','BAKER HUGHES'),
        ('GUF','GULF ENERGY FISHING','GU','GULF ENERGY'),
        ('NFM','NPS FISHING','NER','NESR COMPANY'),
        ('RAC','RAWABI ARCHER','ROG','RAWABI OIL & GAS'),
        ('WFS','WEATHERFORD FISHING SERVICES','WFD','WEATHERFORD'),
        ('WI1','WIS FISHING SERVICE','WIS','WELLBORE INTEGRITY SOLUTIONS'),
        ('WI2','WIS THROUGH TUBING','WIS','WELLBORE INTEGRITY SOLUTIONS'),
        ('WI3','WIS WHIPSTOCK SERVICE','WIS','WELLBORE INTEGRITY SOLUTIONS'),
        ('BWH','BAKER WHIPSTOCK SERVICE','BHG','BAKER HUGHES'),
        ('RWD','RAWABI WILDCAT','ROG','RAWABI OIL & GAS'),
        ('WWD','WEATHERFORD WHIPSTOCK SERVICE','WFD','WEATHERFORD'),
        ('BWT','BAKER HUGHES WELL TESTING','BHG','BAKER HUGHES'),
        ('HTS','HALLIBURTON WELL TESTING','HAL','HALLIBURTON'),
        ('NWT','NPS WELL TESTING','NER','NESR COMPANY'),
        ('SWT','SCHLUMBERGER WELL TESTING','SCH','SCHLUMBERGER'),
        ('WWW','WEATHERFORD WELL TESTING','WFD','WEATHERFORD'),
        ('EX2','EXPRO WELL TESTING','EXP','EXPRO'),
        ('MWT','MANSOORI WELL TESTING','MSO','MANSOORI OILFIELD SERVICES'),
        ('OWT','OILSERV WELL TESTING (ZAMIL)','ZG','ZAMIL GROUP'),
        ('PWS','POWER WELL SERVICES','PWS','POWER WELL SERVICES'),
        ('RTW','RAWABI TRADING WELL TESTING','RTR','AL-RAWABI TRADING'),
        ('NPS','NATIONAL PETROLEUM SERVICES','NER','NESR COMPANY'),
        ('SPL','SAPESCO SLICK LINE','NER','NESR COMPANY'),
        ('MSL','MANSOORI SLICK LINE','MSO','MANSOORI OILFIELD SERVICES'),
        ('OSL','OILSERV SLICKLINE (ZAMIL)','ZG','ZAMIL GROUP'),
        ('SLL','SCHLUMBERGER SLICK LINE','SCH','SCHLUMBERGER'),
        ('CRW','CORETRAX WELLBORE CLEANING','CRT','CORETRAX'),
        ('BWC','BAKER WELLBORE CLEANING SVC','BHG','BAKER HUGHES'),
        ('HWC','HALLIBURTON WELL CLEANING','HAL','HALLIBURTON'),
        ('MIW','MI WELLBORE CLEANING SERVICES','SCH','SCHLUMBERGER'),
        ('SSW','SINOPEC WELLBORE CLEANING','SS','SINOPEC SERVICES'),
        ('SWC','SIE WELLBORE CLEANOUT','SIE','SYNERGY ENERGY'),
        ('MSO','MANSOORI OILFIELD SERVICES','MSO','MANSOORI OILFIELD SERVICES'),
        ('SPC','SAPESCO','SPC','SAPESCO'),
        ('OCT','OILSERV CEMENTING (ZAMIL)','ZG','ZAMIL GROUP'),
        ('BCF','BAKER HUGHES COMPLETION FLUIDS','BHG','BAKER HUGHES'),
        ('TTF','TETRA FILTRATION','TTR','TETRA'),
        ('SG1','SGS FILTRATION','SG0','SGS'),
        ('SG2','SGS WELL TESTING','SG0','SGS'),
        ('WCC','WELLCEM','WCC','WELLCEM'),
        ('RTR','AL-RAWABI TRADING CONT CO','RTR','AL-RAWABI TRADING'),
        ('PR1','PROWELL ENERGY SLICK LINE','PR','PROWELL ENERGY'),
        ('DEM','DELIUM SLICKLINE','DEM','DELIUM SLICKLINE'),
        ('EX1','EXPRO SLICK LINE','EXP','EXPRO'),
        ('NCL','NOV CLOSE LOOP','NOV','NATIONAL OILWELL VARCO'),
        ('GCD','GYRODATA COMPANY','GCD','GYRODATA'),
        ('OGS','OPTIMUM GYRO SERVICES','OGS','OPTIMUM GYRO SERVICES'),
        ('SWC','SIE WELLBORE CLEANOUT','SIE','SYNERGY ENERGY'),
        ('NOJ','NOV JARS & SHOCK TOOLS','NOV','NATIONAL OILWELL VARCO'),
        ('NOR','NORDIC COMPANY','NOR','NORDIC COMPANY'),
        ('TIL','TIW LINER HANGER','TIW','TIW'),
        ('TWC','TIW COMPLETION EQUIPMENTS','TIW','TIW'),
        ('MB2','MBP WELL TESTING','MBP','MOHAMED BARWANI PETROLEUM CO.'),
        ('MBF','MOHAMED BARWANI FILTRATION','MBP','MOHAMED BARWANI PETROLEUM CO.'),
        ('MBP','MOHAMED BARWANI PETROLEUM CO.','MBP','MOHAMED BARWANI PETROLEUM CO.'),
        ('HAE','HIGH ARTIC ENERGY SERVICES','HAE','HIGH ARTIC ENERGY SERVICES'),
        ('ENV','ENVENTURE','ENV','ENVENTURE'),
        ('AKR','AKERS SOLUTIONS','AKR','AKERS SOLUTIONS'),
        ('WTC','WELLTEC','WTC','WELLTEC'),
        ('TGT','TGT OIL AND GAS SERVICES','TGT','TGT OIL AND GAS SERVICES'),
        ('NEY','NEYRFOR','SCH','SCHLUMBERGER'),
        ('GTR','GAS & OIL TECH RETRIEVAL TOOLS','GT1','GAS & OIL TECHNOLOGIES LLC'),
    ]

    result = {}
    for svc_abbr, svc_desc, par_abbr, par_name in RAW:
        svc_abbr = svc_abbr.strip()
        par_abbr = par_abbr.strip()
        par_name = par_name.strip()
        if svc_abbr in _SKIP_ABBREVS or par_name in _SKIP_PARENTS:
            continue
        display = _PARENT_DISPLAY.get(par_abbr, par_name.title().replace('&', '&'))
        cat = _cat(svc_desc)
        if svc_abbr not in result:
            result[svc_abbr] = (display, cat)
    return result

# Built once at import time
ABBREV_LOOKUP = _build_abbrev_map()

# ── Regex-based company/tool patterns ────────────────────────────────────────
# These catch full names, parent abbreviations, and tool brands in free text
COMPANY_PATTERNS = [
    # ── Major international ──────────────────────────────────────
    (r'\bSLB\b',                           'SLB',           'MWD / Directional'),
    (r'\bSchlumberger\b',                  'SLB',           'MWD / Directional'),
    (r'\bSCHLUM\b',                        'SLB',           'MWD / Directional'),
    (r'\bBaker\s*Hughes\b',                'Baker Hughes',  'Completion / MWD'),
    (r'\bBHGE\b',                          'Baker Hughes',  'Completion / MWD'),
    (r'\bHalliburton\b',                   'Halliburton',   'Cementing / MWD'),
    (r'\bWeatherford\b',                   'Weatherford',   'Fishing / Intervention'),
    (r'\bNational\s*Oilwell\b',            'NOV',           'Equipment / Tools'),
    (r'\bNOV\b',                           'NOV',           'Equipment / Tools'),
    # ── Regional / Saudi-specific ────────────────────────────────
    (r'\bNESR\b',                          'NESR',          'Cementing / Stimulation'),
    (r'\bNapesco\b',                       'NAPESCO',       'Rental / Equipment'),
    (r'\bNAPESCO\b',                       'NAPESCO',       'Rental / Equipment'),
    (r'\bRawabi\s+(?:Archer|O&G|Oil)\b',  'Rawabi O&G',    'Fishing / Intervention'),
    (r'\bRawabi\b',                        'Rawabi',        'H2S / Safety / Rental'),
    (r'\bSamaa\b',                         'Samaa',         'Fishing / Intervention'),
    (r'\bCoretrax\b',                      'Coretrax',      'Fishing / Milling'),
    (r'\bExpro\b',                         'Expro',         'Well Testing'),
    (r'\bEXPRO\b',                         'Expro',         'Well Testing'),
    (r'\bAlMansoori\b|\bMansoori\b|\bMSO\b', 'AlMansoori', 'Rental / Coil Tubing'),
    (r'\bTAQA\b',                          'TAQA Group',    'Wireline / Slickline'),
    (r'\bSanjel\b',                        'TAQA Group',    'Cementing'),
    (r'\bGDMC\b|\bGDM\b',                 'GDMC',          'Slickline / Coil Tubing'),
    (r'\bOilserv\b',                       'Oilserv (Zamil)','Directional / Wireline'),
    (r'\bZamil\b',                         'Oilserv (Zamil)','Rental / Services'),
    (r'\bSinopec\b|\bSINOPEC\b',          'Sinopec',       'Solids Control'),
    (r'\bSapesco\b|\bSAPESCO\b',          'Sapesco',       'Tubular Services'),
    (r'\bFranks\b',                        'Franks',        'Casing Running'),
    (r'\bGulf\s*Energy\b',                'Gulf Energy',   'Fishing / Solids Control'),
    (r'\bNabors\b',                        'Nabors',        'MWD / Directional'),
    (r'\bTetra\b|\bTETRA\b',              'Tetra',         'Filtration / Completion'),
    (r'\bInnomax\b|\bInnovex\b',          'Innovex',       'DV Tools / Liner Hangers'),
    (r'\bWelltec\b',                      'Welltec',       'Well Intervention'),
    (r'\bTGT\b',                          'TGT',           'Well Intervention'),
    (r'\bScientific\s*Drilling\b|\bSCD\b','Scientific Drilling','MWD / Directional'),
    # ── Tool/brand → parent ──────────────────────────────────────
    (r'\bNEOSTEER\b',                     'SLB',           'RSS / Directional'),
    (r'\bPOWERDRIVE\b',                   'SLB',           'RSS / Directional'),
    (r'\bORBIT\s+(?:RSS|BHA)\b',         'SLB',           'RSS / Directional'),
    (r'\bGEOSPHERE\b',                    'SLB',           'LWD / Formation Evaluation'),
    (r'\bPOWER\s*PULSE\b',               'SLB',           'MWD'),
    (r'\bSPERRY\b',                       'Halliburton',   'MWD / Directional'),
    (r'\biCRUISE\b',                      'Halliburton',   'RSS / Directional'),
    (r'\bGEO[\-\s]?PILOT\b',             'Halliburton',   'RSS / Directional'),
    (r'\bBAROID\b',                       'Halliburton',   'Drilling Fluids'),
    (r'\bAUTOTRAK\b',                    'Baker Hughes',  'RSS / Directional'),
    (r'\bONTRAK\b',                       'Baker Hughes',  'MWD / LWD'),
    (r'\bSAWAFI\s*BORETS\b',             'Sawafi Borets', 'ESP / Artificial Lift'),
    (r'\bBORETS\b',                       'Sawafi Borets', 'ESP / Artificial Lift'),
    (r'\bMI[\-\s]?SWACO\b',              'SLB',           'Solids Control'),
    (r'\bNewpark\b|\bNEWPARK\b',         'Newpark',       'Drilling Fluids'),
]

# Build compiled pattern list once
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), n, c) for p, n, c in COMPANY_PATTERNS]

# Regex to catch 2-4 char uppercase abbreviations in DDR text
# e.g. "NCS ON LOCATION", "SPR CASING RUNNING", "MCT COIL TUBING ON LOC"
_ABBREV_PATTERN = re.compile(r'\b([A-Z][A-Z0-9]{1,3})\b')

# Exclude false positives: common DDR terms that look like abbreviations
_ABBREV_EXCLUDE = {
    'BHA','RSS','MWD','LWD','TD','WB','RIH','POOH','DP','CSG','CMT','BOP',
    'DST','WH','WHP','WHCP','SCR','TBG','HGR','CHC','LOC','OD','ID','API',
    'BPD','BFPD','PSI','GPM','RPM','WOB','ROP','TFA','TOF','TVD','MD','KOP',
    'EOD','BOD','BOH','GOC','WOC','TOC','WBS','DV','DLS','INC','AZM','GR',
    'RT','KOP','ACE','DIS','BEP','ECD','ESD','SPM','PPB','LPM','STC','CTG',
    'HPHT','AC','DC','MCM','MOV','FTS','HSD','ROT','SRD','STK','TQ','TS',
    'TF','PBL','TJD','DI','DD','WOW','WOC','SSD','ETA','POC','ETD','ESS',
    'PPG','SG','SBT','OK','NO','YES','US','BY','AT','IN','ON','OF','OR',
    'AI','AM','PM','AD','BC','RIG','PU','PD','ND','SD','ED','SC','TC','PC',
    'HC','MC','RC','NC','AC','IC','OC','UC','WC','VC','XC','YC','ZC',
    'KG','MM','CM','KM','FT','MT','ML','LT','ST','WT',
}


def _clean_ctx(text: str) -> str:
    return re.sub(r'^[^A-Za-z0-9$(]+', '', re.sub(r'\s+', ' ', text).strip())


def detect_status(context: str, section_name: str) -> str:
    ctx = context.lower()
    if section_name in ('Next 24h Plan', 'Next Location'):
        return 'planned'
    if re.search(r'\breleased\b|\boff\s+loc\b|\bdeparted\b|\blaid\s+down\b', ctx):
        return 'released'
    if re.search(r'\bplanned\b|\bschedule\b|\bupcoming\b|\bexpected\b', ctx):
        return 'planned'
    if section_name == 'Foreman Remarks':
        return 'on_location'
    return 'on_location'


def extract_competitors(sections: list, rig: str, well: str) -> list:
    mentions = []
    seen = set()

    for sec in sections:
        sec_name = sec.name if hasattr(sec, 'name') else sec.get('name', '')
        sec_text = sec.text if hasattr(sec, 'text') else sec.get('text', '')

        # ── Pass 1: full name / tool brand patterns ───────────────────────────
        for compiled_pat, norm, cat in _COMPILED_PATTERNS:
            for m in compiled_pat.finditer(sec_text):
                raw = m.group(0)
                s = max(0, m.start() - 100)
                if s > 0:
                    sp = sec_text.find(' ', s)
                    if 0 <= sp < m.start():
                        s = sp + 1
                e = min(len(sec_text), m.end() + 100)
                ctx = _clean_ctx(sec_text[s:e])
                status = detect_status(ctx, sec_name)
                key = (norm, sec_name[:30])
                if key in seen:
                    continue
                seen.add(key)
                mentions.append(CompetitorMention(
                    normalized=norm, raw_name=raw, service_category=cat,
                    rig=rig, well=well, status=status, evidence=ctx,
                    section=sec_name,
                    confidence=90 if sec_name == 'Foreman Remarks' else 82,
                ))

        # ── Pass 1b: enrich category based on local context ────────────────
        # E.g. "NOV CENTRIFUGE ON LOC" → override Equipment/Tools to Solids Control
        # This must run after pass 1 to fix context-blind pattern categories
        for mention in mentions:
            if mention.rig != rig or mention.well != well: continue
            ctx_l = mention.evidence.lower()
            if mention.normalized == 'NOV':
                if any(x in ctx_l for x in ['centrifuge','shaker','solid control','barite recov']):
                    mention.service_category = 'Solids Control'
                elif any(x in ctx_l for x in ['liner hanger','completion','bridge plug','casing run']):
                    mention.service_category = 'Completion'
                elif any(x in ctx_l for x in ['directional','mwd','lwd','jar']):
                    mention.service_category = 'MWD / Directional'
            if mention.normalized == 'Halliburton':
                if any(x in ctx_l for x in ['baroid','mud engineer','drilling fluid']):
                    mention.service_category = 'Solids Control'
                elif any(x in ctx_l for x in ['slick line','wireline','logging']):
                    mention.service_category = 'Wireline / Logging'
                elif any(x in ctx_l for x in ['cement','cmt']):
                    mention.service_category = 'Cementing'
            if mention.normalized in ('SLB', 'Baker Hughes', 'Weatherford'):
                if any(x in ctx_l for x in ['mud','drilling fluid','centrifuge']):
                    mention.service_category = 'Solids Control'
                elif any(x in ctx_l for x in ['slick line','wireline','wire line']):
                    mention.service_category = 'Wireline / Logging'
                elif any(x in ctx_l for x in ['cement','cmt']):
                    mention.service_category = 'Cementing'
                elif any(x in ctx_l for x in ['completion','liner','packer','tubing run']):
                    mention.service_category = 'Completion'
            # Rawabi context enrichment — can appear in multiple categories
            if 'rawabi' in mention.normalized.lower():
                if any(x in ctx_l for x in ['archer','fishing tool','overshot','whipstock','fish in hole']):
                    mention.service_category = 'Fishing / Intervention'
                elif any(x in ctx_l for x in ['h2s','safety','monitoring','detection','breathing air']):
                    mention.service_category = 'H2S / Safety'
                elif any(x in ctx_l for x in ['wireline','slickline','slick line']):
                    mention.service_category = 'Wireline / Logging'
                elif any(x in ctx_l for x in ['cement','cmt']):
                    mention.service_category = 'Cementing'
                elif any(x in ctx_l for x in ['well test','flowback','separator']):
                    mention.service_category = 'Well Testing'

        # ── Pass 2: 2-4 char uppercase abbreviation scan ─────────────────────
        for m in _ABBREV_PATTERN.finditer(sec_text):
            abbr = m.group(1)
            if abbr in _ABBREV_EXCLUDE:
                continue
            if abbr not in ABBREV_LOOKUP:
                continue
            norm, cat = ABBREV_LOOKUP[abbr]
            # Skip Aramco / internal
            if 'Aramco' in norm or 'Saudi' in norm:
                continue
            s = max(0, m.start() - 100)
            if s > 0:
                sp = sec_text.find(' ', s)
                if 0 <= sp < m.start():
                    s = sp + 1
            e = min(len(sec_text), m.end() + 100)
            ctx = _clean_ctx(sec_text[s:e])
            status = detect_status(ctx, sec_name)
            key = (norm, sec_name[:30])
            if key in seen:
                continue
            seen.add(key)
            mentions.append(CompetitorMention(
                normalized=norm, raw_name=f"{abbr} ({norm})",
                service_category=cat, rig=rig, well=well,
                status=status, evidence=ctx, section=sec_name,
                confidence=88 if sec_name == 'Foreman Remarks' else 78,
            ))

    return mentions
