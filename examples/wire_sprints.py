"""
wire_sprints.py - End-to-end integration walk-through.

Demonstrates how Sprints 0-12 cooperate in a single session.  No model
calls, no Ollama, no server: this is the LOGICAL pipeline you'd glue
into EarlRuntime.init_storage() / synthesis_node when ready to flip on.

Usage:
    python examples/wire_sprints.py

Reads/writes to a temp directory; leaves your real runtime untouched.
"""

from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "latticed"))

import latticed as L  # noqa: E402


def section(title: str) -> None:
    bar = "-" * 64
    print(f"\n{bar}\n  {title}\n{bar}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="latticed_demo_"))
    try:
        # -----------------------------------------------------------------
        section("Sprint 0 - hardware profile + agent validation")
        profile = L.hardware_profile_detect(force_tier="minimal_gpu")
        agents = L.AgentFactoryRegistry().registry
        report = L.validate_profile_against_agents(profile, agents, strict=True)
        print(f"  tier={profile.tier}  agents={len(agents)}  valid={report.valid}")
        for w in report.warnings[:2]:
            print(f"  WARN: {w}")

        # -----------------------------------------------------------------
        section("Sprint 1 - identity store + privacy seeds")
        store = L.IdentityStore(tmp/"identity.json", user_id="demo").load()
        store.add_fact("I work as a software engineer at a fintech startup.",
                       confidence=0.95)
        store.add_fact("My wife is a high school teacher.",
                       confidence=0.95)
        store.add_fact("My SSN is 999-88-7777.")     # auto-tags HIGH, routes to identity
        store.add_north_star("Lead a team within three years.",
                             domain=L.LifeDomain.CAREER.value, weight=1.5)
        store.add_north_star("Save $250k for a house in 5 years.",
                             domain=L.LifeDomain.FINANCIAL.value, weight=1.2)
        store.add_rule("Be direct with bad news.", priority=200)
        store.save()
        print(f"  {len(store.doc.facts)} fact(s), "
              f"{len(store.doc.north_stars)} north star(s), "
              f"{len(store.doc.constitutional_rules)} rule(s)")
        ssn_sens = [f.sensitivity for f in store.doc.facts if "999" in f.text]
        print(f"  SSN auto-tagged: {ssn_sens[0] if ssn_sens else 'n/a'}")

        # -----------------------------------------------------------------
        section("Sprint 2 - curiosity engine selects next question")
        ledger = L.EngagementLedger(tmp/"curiosity.json")
        engine = L.CuriosityEngine(store, ledger, max_per_hour=1, max_per_day=3)
        sel = engine.select_next_question()
        if sel:
            q, gap, gain = sel
            print(f"  next-question: {q!r}")
            print(f"  gap={gap.domain}/{gap.gap_type} expected_info_gain={gain:.3f}")
            engine.record_question_asked(q, gap, gain)
            engine.record_response(q, answered=True, response_excerpt="Sure.")
            print(f"  ledger: {len(ledger.entries)} entry, response_rate={ledger.response_rate():.2f}")

        # -----------------------------------------------------------------
        section("Sprint 3 - voice preamble for life_coach")
        preamble = L.build_voice_preamble("life_coach", store, ledger,
                                          include_curiosity_hint=True)
        print(preamble[:400] + (" ..." if len(preamble) > 400 else ""))

        # -----------------------------------------------------------------
        section("Sprint 4 - voice evolution from a positive signal")
        voice = L.VoiceEvolutionEngine(tmp/"voice.json")
        voice.record_interaction(L.EngagementSignal(
            agent_id="fast_mentor", output_chars=180,
            user_explicit_positive=True,
        ))
        p = voice.profile_for("fast_mentor")
        print(f"  fast_mentor brevity_pref={p.brevity_pref:.3f}  "
              f"warmth_pref={p.warmth_pref:.3f}  curiosity_mult={p.curiosity_mult:.3f}")

        # -----------------------------------------------------------------
        section("Sprint 5 - identity synthesis + portrait")
        synth = L.IdentitySynthesizer(store)
        portrait = synth.synthesize_portrait()
        print(f"  {portrait.one_line_summary}")
        for dom, ds in list(portrait.domains.items())[:3]:
            print(f"  {ds.narrative}")

        # -----------------------------------------------------------------
        section("Sprint 6 - tiered memory routing")
        ms = L.MemoryStore()
        for txt in [
            "I cook on weekends.",
            "My password is hunter2.",
            "I work as an engineer at a fintech startup.",
            "Reminder: dentist on Tuesday.",
        ]:
            tier, sens, dom = L.MemoryRouter.route(txt)
            ms.add(L.MemoryRecord(text=txt, tier=tier, sensitivity=sens, domain=dom,
                                  confidence=0.8))
            print(f"  '{txt[:40]}...' -> tier={tier:8s} sens={sens:6s} domain={dom}")

        # -----------------------------------------------------------------
        section("Sprint 7 - performance log + fingerprint-based model select")
        perf = L.PerformanceLog()
        for ms_ in [10.0, 14.0, 22.0, 8.0]:
            perf.record("intent_router", ms_)
        for ms_ in [220.0, 280.0, 310.0]:
            perf.record("life_coach", ms_)
        agg = perf.aggregate("life_coach")
        print(f"  life_coach: p50={agg['p50']:.0f}ms  p90={agg['p90']:.0f}ms")
        print(f"  slowest: {perf.slowest_nodes(top_k=2)}")

        # -----------------------------------------------------------------
        section("Sprint 8 - audited egress via privacy gate")
        consumer = L.Consumer("demo_consumer", "Demo Consumer")
        grant = L.ConsumerGrant(
            consumer_id="demo_consumer",
            allowed_domains=[L.LifeDomain.CAREER.value],
            sensitivity_ceiling=L.Sensitivity.MEDIUM.value,
            allowed_destinations=["remote_api"],
        )
        audit = L.AccessAuditLog(tmp/"audit.jsonl")
        for txt in [
            "Working on the new launch.",                  # LOW + career -> allow
            "My wife is a teacher.",                        # MEDIUM + relationships -> deny (scope)
            "My password is hunter2.",                      # SECRET -> deny (router veto)
        ]:
            ok, reason, _ = L.audited_egress(txt, consumer, grant, "remote_api", audit)
            print(f"  '{txt[:35]:35s}' -> {'ALLOW' if ok else 'DENY ':5s}  {reason}")

        # -----------------------------------------------------------------
        section("Sprint 9 - MCP server dispatch")
        srv = L.MCPServer(store, audit, synthesizer=synth, curiosity=engine)
        srv.register_consumer(consumer,
                              L.ConsumerGrant(consumer_id="demo_consumer",
                                              sensitivity_ceiling=L.Sensitivity.LOW.value,
                                              allowed_destinations=["mcp"]))
        resp = srv.handle(L.MCPRequest(method="resources/read",
                                        consumer_id="demo_consumer",
                                        params={"uri": "identity://portrait"}))
        print(f"  resources/read identity://portrait ok={resp.ok}")
        print(f"  -> {resp.result}")

        # -----------------------------------------------------------------
        section("Sprint 10 - Two Mes Model + tension")
        model = L.TwoMesModel.from_store(store)
        for dom, score in L.high_tension_domains(model)[:3]:
            print(f"  high tension: {dom:14s}  score={score:.2f}")

        # -----------------------------------------------------------------
        section("Sprint 11 - aspects + cross-memory recombination")
        store.add_fact("I'm learning Rust on weekends.",
                       domain=L.LifeDomain.GROWTH.value, confidence=0.85)
        store.add_fact("My team adopted Rust for new services.",
                       domain=L.LifeDomain.CAREER.value, confidence=0.9)
        idx = L.AspectIndex.from_store(store)
        print(f"  aspects observed: {idx.names()}")
        insights = L.recombine_memory(store, top_k=3)
        for ins in insights:
            print(f"  link {ins.domain_a:14s} <-> {ins.domain_b:14s}  "
                  f"score={ins.score:.2f}  terms={ins.link_terms}")

        # -----------------------------------------------------------------
        section("Sprint 12 - business mode routing")
        biz = L.BusinessStore(tmp/"business.json")
        biz.register(L.BusinessProfile(business_id="acme",
                                        display_name="Acme LLC",
                                        legal_entity="LLC", role="founder"),
                     set_active=True)
        for txt in [
            "Our company hit $20k MRR this month.",
            "My wife and I went hiking.",
            "Time to refine our pricing for the launch.",
        ]:
            route, bid = L.route_fact(txt, biz)
            print(f"  '{txt[:45]:45s}' -> {route} ({bid or '-'})")

        # -----------------------------------------------------------------
        section("Wiring complete")
        print("  Every sprint module loaded, executed, and produced output.")
        print("  The runtime pipeline does NOT yet call any of these.  Flipping")
        print("  the activation switches is a separate, scoped change per sprint.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
