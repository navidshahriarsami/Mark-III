"""
MARK III Cognitive Council — Live Demo
Executive: GPT-OSS 120B (OpenInference) — no Anthropic key required
"""
import asyncio, os, sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("OPENROUTER_API_KEY", "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")

from app.services.council.council_manager import get_council
from app.services.council.model_router    import classify_query

QUERY = "How should I improve MARK III as an AI operating system? Give me a concrete development roadmap."

async def main():
    print("=" * 65)
    print("  MARK III — Cognitive Council Demo")
    print("=" * 65)
    print(f"\n  Query: {QUERY}\n")

    # Step 1: Route (local, 0ms, 0 API calls)
    t0       = time.monotonic()
    analysis = await classify_query(QUERY)
    route_ms = (time.monotonic() - t0) * 1000

    roles = [r.value for r in analysis.roles]
    print(f"  Routing       {route_ms:.1f}ms   [local rules — 0 API calls]")
    print(f"  Specialists   {roles}")
    print(f"  Complexity    {analysis.complexity}")
    print(f"  Tags          {analysis.domain_tags}")
    print()

    # Step 2: Council consult (specialists + Executive)
    print("  Consulting council ...\n")
    council = get_council()
    session = await council.consult(
        query        = QUERY,
        context_hint = "User is building MARK III — a personal AI OS for Windows. Currently at v0.14.0.",
        device_id    = "demo",
    )

    # Step 3: Show specialist results
    print("  SPECIALIST RESPONSES:")
    print("  " + "-" * 61)
    for r in session.specialist_responses:
        if r.role == "executive":
            continue
        status = "OK  " if not r.error else "FAIL"
        text   = (r.text[:120].replace("\n", " ") + "...") if len(r.text) > 120 else r.text.replace("\n", " ")
        print(f"  [{status}] {r.name:14} {r.latency_ms:6.0f}ms  {r.provider}/{r.model.split('/')[-1]}")
        if text:
            print(f"          {text}")
        elif r.error:
            print(f"          ERROR: {r.error[:80]}")
        print()

    # Step 4: Final answer
    exec_r = session.executive_response
    print("  EXECUTIVE SYNTHESIS:")
    print(f"  [{exec_r.provider}/{exec_r.model.split('/')[-1]}]  {exec_r.latency_ms:.0f}ms")
    print("  " + "-" * 61)
    print()
    # Word-wrap at 63 chars
    words, line = session.final_answer.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > 63:
            print(f"  {line}")
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        print(f"  {line}")
    print()
    print("  " + "-" * 61)
    print(f"  Total latency   {session.total_latency_ms:.0f}ms")
    print(f"  Specialists     {session.specialists_used} called, {session.specialists_accepted} accepted")
    print(f"  Total cost      ${session.total_cost_usd:.5f}")
    print("=" * 65)

asyncio.run(main())
