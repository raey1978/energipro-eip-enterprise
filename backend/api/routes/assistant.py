"""
EIP v5.0 — AI Sales Assistant
Answers commercial questions using the platform's intelligence data.
Powered by Anthropic API with structured context injection.
"""
import json, logging
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from core.auth import get_current_user
from core.database import get_db

router = APIRouter()
logger = logging.getLogger("eip.assistant")


class AssistantQuery(BaseModel):
    question: str
    context_filter: dict = {}   # Optional: {product_line, field, rig}


def _build_context(data: dict, query: str) -> str:
    """Build executive BD context for the AI assistant."""
    opps   = data.get("opportunities", [])
    comps  = data.get("competitors", [])
    report_date = data.get("report_date", "latest")

    from collections import Counter
    from engines.intelligence.revenue_engine import calculate_revenue_intelligence

    pl_counts   = Counter(o.get("product_line","") for o in opps)
    comp_counts  = Counter(c.get("normalized","") for c in comps if c.get("normalized"))
    imm_opps    = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
    high_conf   = [o for o in opps if o.get("confidence",0) >= 85]
    accepted    = [o for o in opps if o.get("validation_status") == "accepted"]
    no_comp     = [o for o in opps if not o.get("competitor") and o.get("urgency") in ("immediate","5_days","7_days")]

    total_val   = sum(o.get("estimated_value",0) for o in opps)
    imm_val     = sum(o.get("estimated_value",0) for o in imm_opps)

    # Calculate weighted pipeline
    weighted = 0
    for o in opps[:50]:
        try:
            ri = calculate_revenue_intelligence(o)
            weighted += ri.get("weighted_pipeline_value", 0)
        except Exception:
            pass

    ctx_lines = [
        f"DDR Report Date: {report_date}",
        f"Total Opportunities Detected: {len(opps)}",
        f"IMMEDIATE/5-DAY Actions Required: {len(imm_opps)} (${imm_val:,.0f} at risk)",
        f"High Confidence (≥85%): {len(high_conf)}",
        f"Human-Validated (Accepted): {len(accepted)}",
        f"Uncontested (No Competitor): {len(no_comp)}",
        f"",
        f"REVENUE ESTIMATES:",
        f"  Total Pipeline (Expected): ${total_val:,.0f}",
        f"  Weighted Pipeline: ${weighted:,.0f}",
        f"",
        f"Top Product Lines: {', '.join(f'{pl}({cnt})' for pl, cnt in pl_counts.most_common(5))}",
        f"Top Competitors: {', '.join(f'{c}({n})' for c, n in comp_counts.most_common(5))}",
        f"",
        f"TOP 12 OPPORTUNITIES (by confidence):",
    ]
    for o in sorted(opps, key=lambda x: (-x.get("confidence",0), x.get("urgency","future") in ("immediate","5_days")))[:12]:
        comp_str = f" vs {o.get('competitor','')}" if o.get('competitor') else " (NO COMPETITOR — PRIMARY APPROACH)"
        val_str  = f" ${o.get('estimated_value',0):,.0f}" if o.get("estimated_value") else ""
        ctx_lines.append(
            f"  [{o.get('urgency','?').upper():12s}] {o.get('product_line',''):22s} "
            f"| {o.get('rig','?'):8s}/{o.get('well','?'):15s} "
            f"| {o.get('field','?'):12s} "
            f"| Conf:{o.get('confidence',0):3d}%"
            f"{comp_str}{val_str}"
        )

    return "\n".join(ctx_lines)


@router.post("/ask")
async def ask_assistant(
    body: AssistantQuery,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    AI Sales Assistant — answers commercial questions using current DDR intelligence.
    The response is streamed back as a text answer with evidence references.
    """
    if not body.question or len(body.question.strip()) < 5:
        raise HTTPException(400, "Question is too short.")
    if len(body.question) > 500:
        raise HTTPException(400, "Question is too long (max 500 characters).")

    data    = getattr(request.app.state, "intelligence_store", {})
    context = _build_context(data, body.question)

    system_prompt = """You are the AI Business Development Copilot for EIP — the world's leading AI Revenue Intelligence & Business Development Platform for Oilfield Service Companies.

You help BD teams and executives make commercial decisions using live DDR intelligence data.

YOUR ROLE:
- Help BD teams WIN MORE WORK by surfacing the right opportunities at the right time
- Answer commercial questions with precision and evidence
- Think like a 20-year experienced BD Director in oilfield services
- Always recommend specific, actionable next steps

YOU HAVE ACCESS TO:
- All DDR-detected opportunities with confidence scores and evidence
- Competitor presence data by rig and product line
- Revenue potential estimates by product line
- Customer intelligence from field activity
- Pipeline status and stage information

RULES — NEVER BREAK THESE:
- ONLY use data from the provided context. Never invent rigs, wells, values, or competitors.
- When data is insufficient, say so explicitly
- Quantify every recommendation where possible ($, %, days)
- ALWAYS end with 2-3 specific, named actions with owners
- Never present estimates as confirmed facts — use "estimated", "approximately", "based on DDR data"
- Be direct — executives need answers in seconds, not paragraphs

COMMON BD QUESTIONS YOU HANDLE:
• "What should my team do this week?" → Prioritise by urgency and revenue
• "Which customer needs immediate attention?" → Identify by rig activity
• "Which proposal should we prioritise?" → Rank by qualification score and value
• "Where is our biggest revenue opportunity?" → Aggregate by PL and field
• "Which competitor is strongest?" → Analyse by mention frequency and field coverage
• "Why should we pursue this?" → Reference DDR evidence specifically"""

    user_message = f"""Current Intelligence Context:
{context}

Question: {body.question}"""

    # Call Anthropic API
    import httpx, os
    api_key = os.environ.get("ANTHROPIC_API_KEY","")

    if not api_key:
        # Return a structured response without AI when no API key configured
        return _fallback_response(body.question, data)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-sonnet-4-6",
                    "max_tokens": 800,
                    "system":     system_prompt,
                    "messages":   [{"role":"user","content":user_message}],
                }
            )
            if resp.status_code != 200:
                logger.warning("assistant_api_error", extra={"status": resp.status_code})
                return _fallback_response(body.question, data)

            content = resp.json().get("content",[])
            answer  = " ".join(c.get("text","") for c in content if c.get("type")=="text")
    except Exception as e:
        logger.error("assistant_error", extra={"error": str(e)})
        return _fallback_response(body.question, data)

    logger.info("assistant_query", extra={
        "user": user.get("email"), "question_len": len(body.question)
    })

    return {
        "question": body.question,
        "answer":   answer,
        "powered_by": "AI (Claude)",
        "data_date":  data.get("report_date","unknown"),
        "context_size": len(data.get("opportunities",[])),
    }


def _fallback_response(question: str, data: dict) -> dict:
    """Rule-based fallback when AI API is unavailable."""
    opps  = data.get("opportunities",[])
    comps = data.get("competitors",[])
    q     = question.lower()

    from collections import Counter

    if any(w in q for w in ["focus","priority","immediate","urgent","action"]):
        imm = [o for o in opps if o.get("urgency") in ("immediate","5_days")]
        if imm:
            lines = [f"• {o.get('product_line')} on {o.get('rig')}/{o.get('well')} — ${o.get('estimated_value',0):,.0f}" for o in imm[:5]]
            answer = f"Focus on {len(imm)} immediate/5-day opportunities:\n" + "\n".join(lines)
        else:
            answer = "No immediate opportunities detected in current data."

    elif any(w in q for w in ["competitor","who is winning","dominant","strongest"]):
        counts = Counter(c.get("normalized","") for c in comps if c.get("normalized"))
        top    = counts.most_common(3)
        if top:
            lines  = [f"• {n}: {c} rig detections" for n,c in top]
            answer = "Most active competitors:\n" + "\n".join(lines)
        else:
            answer = "No competitors detected in current data."

    elif any(w in q for w in ["field","region","area","where"]):
        from collections import Counter as C2
        fields = C2(o.get("field","") for o in opps if o.get("field"))
        top    = fields.most_common(3)
        if top:
            lines  = [f"• {f}: {n} opportunities" for f,n in top]
            answer = "Most active fields:\n" + "\n".join(lines)
        else:
            answer = "Field data not available in current dataset."

    elif any(w in q for w in ["product","service line","what service"]):
        from collections import Counter as C3
        pls = C3(o.get("product_line","") for o in opps)
        top = pls.most_common(5)
        lines  = [f"• {pl}: {n} opportunities" for pl,n in top]
        answer = "Top product lines by opportunity count:\n" + "\n".join(lines)

    else:
        total = len(opps)
        imm   = sum(1 for o in opps if o.get("urgency") in ("immediate","5_days"))
        val   = sum(o.get("estimated_value",0) for o in opps)
        answer = (f"Current intelligence: {total} opportunities (${val:,.0f} pipeline), "
                  f"{imm} require immediate action. "
                  f"Configure your Anthropic API key for full AI-powered answers.")

    return {
        "question":    question,
        "answer":      answer,
        "powered_by":  "Rule-based (configure ANTHROPIC_API_KEY for AI mode)",
        "data_date":   data.get("report_date","unknown"),
        "context_size":len(opps),
    }


@router.get("/suggested-questions")
async def suggested_questions(user: dict = Depends(get_current_user)):
    """Return suggested questions for the assistant based on current data."""
    return [
        "Which operators should we visit next week?",
        "Show me opportunities above 85% confidence.",
        "Which competitor is most active this week?",
        "What should our sales team focus on today?",
        "Which rigs are entering completion phase?",
        "Where is SLB most active and how do we displace them?",
        "Which product lines have the highest demand?",
        "Which fields have the most uncontested opportunities?",
        "What is the total value of immediate opportunities?",
        "Which opportunities have no competitor detected?",
    ]
