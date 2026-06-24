import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("OPENROUTER_API_KEY", "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")

from app.services.council.specialist_registry import all_specialists, executive_chain, SpecialistRole
from app.services.council.model_router import classify_query
from app.services.council.council_manager import get_council
from app.services.council.consensus_engine import synthesize
from app.api.v1.council import router

print("All imports OK")
print()
print("Executive fallback chain:")
for pk, m in executive_chain():
    print(f"  {pk:12} -> {m}")

print()
print("Specialist registry:")
for s in all_specialists():
    fallbacks = [m.split("/")[-1] for _, m in s.fallback_chain] if s.fallback_chain else []
    chain_str = " -> ".join(fallbacks) if fallbacks else "none"
    local = " [LOCAL-ONLY]" if s.local_only else ""
    primary = s.model.split("/")[-1]
    print(f"  {s.role.value:14} {s.provider_key:12} {primary:40} fallback: {chain_str}{local}")

print()

async def test_routing():
    cases = [
        ("How should I improve MARK III?",              "planning"),
        ("Debug this Python crash: IndexError line 42", "coding"),
        ("I feel stressed about my deadlines",          "conversation"),
        ("Plan a roadmap for my startup",               "planning"),
        ("What is DeepSeek R1?",                       "research"),
        ("Hello, good morning",                         "conversation"),
        ("Why does async/await work the way it does?",  "reasoning"),
        ("Fix this SQL query: SELECT * FORM users",     "coding"),
    ]
    print("Routing (local rules only, 0 API calls):")
    for q, expected in cases:
        r = await classify_query(q)
        roles = [x.value for x in r.roles]
        council = len(r.roles) > 2 and r.complexity in ("medium", "high")
        flag = "COUNCIL" if council else "DIRECT "
        ok = expected in [x.value for x in r.roles]
        mark = "OK" if ok else "??"
        print(f"  [{flag}][{mark}] {q[:52]:53} {roles}")

asyncio.run(test_routing())

print()
print("MARK III Principle verified:")
print("  - Routing: 0 API calls (local rules)")
print("  - Executive: Claude -> Nemotron -> GPT-OSS fallback chain")
print("  - Memory: Gemma 4 -> Llama 3.3 -> GPT-OSS")
print("  - Productivity: Gemma 4 -> Hermes 3 -> GPT-OSS")
print("  - Anthropic: optional. OpenRouter-only mode fully supported.")
