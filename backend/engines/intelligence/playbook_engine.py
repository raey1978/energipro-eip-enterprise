"""
EIP v5.1 — Commercial Playbook Engine
Product-line specific battle cards, displacement strategies, and sales scripts.
"""

PLAYBOOKS = {
    "MWD / Directional": {
        "positioning": "EnergiPro provides MWD/LWD services with proven Saudi Aramco track record. Our directional drillers are experienced in HP/HT and complex trajectories.",
        "key_differentiators": [
            "Proven performance in Saudi Aramco wells",
            "Dedicated directional drillers — not subcontracted",
            "Real-time data transmission capability",
            "Emergency response within 4 hours",
        ],
        "common_competitors": ["SLB (Sperry/NeoSteer)", "Halliburton (iCruise)", "Baker Hughes (AutoTrak)", "NESR", "Scientific Drilling"],
        "displacement_strategy": {
            "SLB":          "Emphasise local support, faster mobilisation, and competitive pricing on accessories.",
            "Halliburton":  "Focus on flexibility and responsiveness — Halliburton is large and slow to react.",
            "Baker Hughes": "Highlight our local inventory and no minimum contract length.",
            "NESR":         "Match on price, differentiate on data quality and directional expertise.",
        },
        "qualification_questions": [
            "What trajectory complexity is planned? (vertical/S-curve/horizontal/ERD)",
            "What is the formation type and expected lithology?",
            "Is an RSS or standard motor BHA required?",
            "What is the planned lateral length?",
            "Is real-time data transmission required?",
            "What is the expected H2S exposure?",
        ],
        "value_proposition": "Directional drilling windows are short and costly to miss. Every day of delay costs the operator in rig time. We offer fast mobilisation, proven performance, and competitive unit rates.",
        "talking_points": [
            "Our MWD engineers hold Aramco SACP certification",
            "We stock RSS tools locally — no import lead time",
            "We provide real-time data via satellite to the drilling supervisor",
        ],
        "objection_handlers": {
            "We already have SLB on contract": "We're not asking to replace them — we can compete for accessories and provide backup coverage. Let's start with one well.",
            "Your price is too high": "Our price includes local support and 24/7 engineer on standby. SLB's add-ons often push the real cost 20-30% higher.",
            "We need Aramco-approved vendor": "EnergiPro is a registered Aramco supplier. We can provide our SC number immediately.",
        },
    },

    "Completion": {
        "positioning": "EnergiPro supplies completion accessories, liner hangers, and tubular running services for Saudi Aramco wells.",
        "key_differentiators": [
            "Local inventory of completion accessories",
            "Experienced completion crews with Aramco track record",
            "Competitive pricing on liner hangers and packers",
        ],
        "common_competitors": ["SLB","Baker Hughes","Halliburton","Weatherford","Coretrax","NOV","Franks"],
        "displacement_strategy": {
            "SLB":          "Focus on accessory packages — SLB often neglects small accessories. We can supply and support the full completion package.",
            "Weatherford":  "Weatherford has capacity constraints. Offer reliability and faster delivery.",
            "Coretrax":     "Coretrax specialises in whipstock/milling. Position EnergiPro for the completion accessories they don't focus on.",
        },
        "qualification_questions": [
            "Is this a liner or full string completion?",
            "What are the liner hanger specifications?",
            "Is a float collar and shoe required?",
            "What packers are in the completion design?",
            "Who is running the completion string?",
            "What is the completion date target?",
        ],
        "value_proposition": "Completion accessories are critical path items. Delays cost the operator $50K-$200K/day in rig time. We stock locally and deliver within 24 hours.",
        "talking_points": [
            "We hold buffer stock of the top 20 completion accessories in KSA",
            "Our completion engineers are API 5CT and API 11B certified",
            "We can deliver emergency accessories to any KSA location within 24 hours",
        ],
        "objection_handlers": {
            "We get completion tools from the main contractor": "We can supply direct to you at lower cost — you don't need to pay the contractor markup.",
            "We need Aramco Material Master numbers": "All our products are pre-registered in the Aramco system. We can provide the material numbers today.",
        },
    },

    "Fishing / Intervention": {
        "positioning": "EnergiPro provides fishing and intervention services with fast mobilisation — critical for minimising downtime on stuck pipe and BHA recovery.",
        "key_differentiators": [
            "24-hour emergency response",
            "Local fishing tool inventory",
            "Experienced fishing supervisors",
            "Full range from overshots to whipstocks",
        ],
        "common_competitors": ["SLB","Baker Hughes","Weatherford","NESR","Rawabi Archer","WIS","Coretrax","Arabian Est. Fishing"],
        "displacement_strategy": {
            "SLB":      "SLB fishing response is slow (24-48hr mobilisation). We can mobilise within 12 hours.",
            "Rawabi":   "Rawabi focuses on H2S safety — position for complex fishing jobs they can't handle.",
            "Coretrax": "Coretrax is strong on milling. Position EnergiPro on overshot recovery and junk removal.",
        },
        "qualification_questions": [
            "What is the fish type and depth?",
            "What is the hole size and formation?",
            "Is there H2S present?",
            "What is the estimated stuck point?",
            "Has backoff or jarring been attempted?",
            "What is the rig's current standby rate?",
        ],
        "value_proposition": "Every hour of stuck pipe costs the operator $10K-$50K. Fast, effective fishing directly reduces well cost. Speed of response is the key differentiator.",
        "talking_points": [
            "We have a dedicated fishing supervisor on 24-hour call in KSA",
            "Our fishing tool inventory covers 99% of standard fishing jobs",
            "We prepare a detailed technical fishing programme before mobilisation",
        ],
        "objection_handlers": {
            "We need to get Aramco approval first": "We are on the Aramco Approved Vendor List. Share our SC number with your team — approval is instant.",
            "The contractor is already on the way": "We can be backup. If their first attempt fails, we are ready to mobilise immediately.",
        },
    },

    "Cementing": {
        "positioning": "EnergiPro provides cementing accessories, additives, and completion cementing support across KSA.",
        "key_differentiators": [
            "Local supply of cementing accessories",
            "Fast delivery to remote locations",
            "Competitive pricing on bulk additives",
        ],
        "common_competitors": ["SLB","Halliburton","Baker Hughes","NESR","TAQA Group","Oilserv (Zamil)"],
        "displacement_strategy": {
            "Halliburton": "Halliburton dominates cementing services but their accessories are overpriced. We supply direct at 20-30% lower cost.",
            "NESR":        "NESR is growing fast but has supply chain gaps. Position on accessory reliability.",
        },
        "qualification_questions": [
            "What casing size and cement job type?",
            "What is the planned cement slurry design?",
            "Are cement additives required?",
            "What is the BHP/BHT?",
            "Is this a primary cement or remedial squeeze?",
        ],
        "value_proposition": "Cement job failure leads to costly remedial work. Quality cementing accessories and additives ensure job success on the first attempt.",
        "talking_points": [
            "Our cementing accessories are API-certified and Aramco-registered",
            "We can supply emergency cement additives within 6 hours anywhere in KSA",
        ],
        "objection_handlers": {
            "We use the cementing company's own additives": "Most cementing companies mark up additives 40-60%. Buy direct from us and save.",
        },
    },

    "Well Testing": {
        "positioning": "EnergiPro supports well testing operations with equipment, consumables, and technical expertise.",
        "key_differentiators": [
            "Local well testing equipment",
            "Experienced test supervisors",
            "Competitive rates on testing packages",
        ],
        "common_competitors": ["Expro","SLB","Halliburton","Baker Hughes","NESR","AlMansoori","SGS"],
        "displacement_strategy": {
            "Expro":     "Expro is the market leader but expensive. We can match on equipment quality at 15-20% lower cost.",
            "AlMansoori":"AlMansoori has strong relationships — position on technical capability and data quality.",
        },
        "qualification_questions": [
            "What is the test objective (DST / production test / inflow test)?",
            "What are the expected flow rates and pressures?",
            "Is H2S present?",
            "What surface separation equipment is needed?",
            "Is flaring permitted or is a closed system required?",
        ],
        "value_proposition": "Well test data drives billion-dollar field development decisions. Data quality and equipment reliability are non-negotiable.",
        "talking_points": [
            "Our well test equipment is fully calibrated and ATEX-certified",
            "We provide real-time data transmission to the client's engineers",
        ],
        "objection_handlers": {
            "We have Expro on long-term contract": "We can price accessories and support equipment competitively. Start with one DST.",
        },
    },

    "Solids Control": {
        "positioning": "EnergiPro supplies solids control equipment — centrifuges, shakers, and mud cleaning systems for Saudi Aramco operations.",
        "key_differentiators": [
            "Local centrifuge and shaker inventory",
            "24-hour field service support",
            "Competitive daily rental rates",
        ],
        "common_competitors": ["NOV","SLB (MI-SWACO)","Halliburton (Baroid)","Baker Hughes","Gulf Energy","AlMansoori","Sinopec"],
        "displacement_strategy": {
            "NOV":     "NOV dominates with Brandt brand. Position on price and local service.",
            "SLB":     "SLB/MI-SWACO bundles solids control with mud engineering — separate the contract and supply direct.",
        },
        "qualification_questions": [
            "What is the mud weight range?",
            "What is the planned drill rate and circulation rate?",
            "How many centrifuges are planned on the rig?",
            "Is waste management required?",
            "What is the rig contract (full service or rental only)?",
        ],
        "value_proposition": "Good solids control reduces mud costs and improves ROP. Poor solids control is the single largest controllable cost in drilling.",
        "talking_points": [
            "Our centrifuges recover 95%+ of barite — reducing mud cost significantly",
            "We provide a dedicated solids control engineer on each location",
        ],
        "objection_handlers": {
            "We use the mud company's own solids control": "Most mud companies mark up solids control equipment 30%. Separate the supply and save.",
        },
    },

    "H2S / Safety": {
        "positioning": "EnergiPro provides H2S monitoring packages, breathing air systems, and safety equipment for sour service operations.",
        "key_differentiators": [
            "Aramco-certified H2S monitoring equipment",
            "Experienced H2S safety supervisors",
            "Fast mobilisation to sour service locations",
        ],
        "common_competitors": ["Rawabi","Total Safety Company","NESR","AlMansoori","Sinopec"],
        "displacement_strategy": {
            "Rawabi": "Rawabi is very strong in H2S — position on pricing and service quality for supplementary packages.",
        },
        "qualification_questions": [
            "What is the maximum expected H2S concentration?",
            "How many personnel will be on the breathing air system?",
            "Is continuous monitoring or spot-check monitoring required?",
            "What is the site evacuation plan?",
            "Is SCBA or airline breathing required?",
        ],
        "value_proposition": "H2S safety is non-negotiable and life-critical. Certified equipment and trained supervisors protect your personnel and prevent costly well shutdowns.",
        "talking_points": [
            "Our H2S monitoring equipment is ATEX Zone 1 certified",
            "All our H2S supervisors hold IWCF and H2S Alive certification",
        ],
        "objection_handlers": {
            "Rawabi is already on our vendor list for H2S": "We can supply supplementary H2S packages for additional locations or overflow needs.",
        },
    },

    "Wireline / Logging": {
        "positioning": "EnergiPro supports wireline and slickline operations with equipment, tools, and trained crews.",
        "key_differentiators": [
            "Local wireline equipment",
            "Trained slickline operators",
            "Competitive service rates",
        ],
        "common_competitors": ["SLB","Halliburton","Baker Hughes","Weatherford","NESR","GDMC","TAQA Group","Oilserv (Zamil)"],
        "displacement_strategy": {
            "SLB":  "SLB wireline is expensive and has long mobilisation times. Position on speed and price.",
            "GDMC": "GDMC focuses on slickline. Position EnergiPro for wireline logging services.",
            "NESR": "NESR is growing but has equipment availability gaps. Position on reliability.",
        },
        "qualification_questions": [
            "Is this e-line or slickline?",
            "What logging suite is planned?",
            "What is the maximum well deviation?",
            "Is the well under pressure?",
            "What surface equipment is required?",
        ],
        "value_proposition": "Wireline data quality drives well completion decisions. Equipment reliability and data accuracy are critical.",
        "talking_points": [
            "Our wireline trucks are fully equipped for 10,000m depth",
            "We provide digital data delivery within 2 hours of job completion",
        ],
        "objection_handlers": {
            "We need to match the logging programme from the drill plan": "Send us the logging programme — we can confirm tool availability and pricing within 24 hours.",
        },
    },

    "Rental / Intervention": {
        "positioning": "EnergiPro provides downhole rental tools, jars, shock tools, and coil tubing accessories for Saudi Aramco operations.",
        "key_differentiators": [
            "Broad inventory of rental tools",
            "Competitive daily rental rates",
            "Fast delivery and make-ready service",
        ],
        "common_competitors": ["NOV","SLB","Baker Hughes","NAPESCO","NESR","AlMansoori","Franks","TAQA Group"],
        "displacement_strategy": {
            "NAPESCO": "NAPESCO has the largest rental tool fleet in KSA — compete on price for specific tools.",
            "NOV":     "NOV marks up rental tools significantly. We can match on jars and shock tools at lower cost.",
        },
        "qualification_questions": [
            "What tools are needed and for how long?",
            "What is the planned BHA configuration?",
            "What is the maximum expected shock loading?",
            "Is coil tubing or through-tubing intervention planned?",
            "What are the wellbore conditions?",
        ],
        "value_proposition": "The right rental tool prevents BHA failures and reduces non-productive time. Every NPT event costs $10K-$100K depending on the rig.",
        "talking_points": [
            "We inspect and pressure-test all rental tools before dispatch",
            "Our tool returns include a full inspection report",
        ],
        "objection_handlers": {
            "We rent everything from NAPESCO on a frame agreement": "We can supply tools not covered by the NAPESCO frame at short notice.",
        },
    },
}


def get_playbook(product_line: str) -> dict:
    """Get the commercial playbook for a product line."""
    return PLAYBOOKS.get(product_line, {
        "positioning": f"EnergiPro provides {product_line} services.",
        "key_differentiators": [],
        "common_competitors": [],
        "displacement_strategy": {},
        "qualification_questions": [],
        "value_proposition": "",
        "talking_points": [],
        "objection_handlers": {},
    })


def get_all_playbook_names() -> list:
    return list(PLAYBOOKS.keys())
