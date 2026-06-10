"""Phase 3 Research Bets - Tournament + Speculative Decoder + Prompt Evolution."""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))

def _tmp(): return Path(tempfile.mkdtemp(prefix="phase3_"))


# ---------- A6 Tournament ----------
def test_tournament_winner_by_wins():
    branches = [
        L.SpeculativeBranch(model_name="A", output="short",                latency_ms=50),
        L.SpeculativeBranch(model_name="B", output="medium length output", latency_ms=80),
        L.SpeculativeBranch(model_name="C", output="the longest output of the bunch by far", latency_ms=120),
    ]
    rep = L.Tournament().run(branches)
    check("tournament has 3 pairs (3-choose-2)", len(rep.pairs) == 3, f"got {rep.pairs}")
    check("winner is C (longest content)",
          rep.winner and rep.winner.model_name == "C",
          f"got {rep.winner.model_name if rep.winner else None}")
    check("standings sorted by wins desc",
          rep.standings[0][1] >= rep.standings[-1][1])


def test_tournament_tie_breaks_by_latency():
    branches = [
        L.SpeculativeBranch(model_name="fast", output="same length text", latency_ms=50),
        L.SpeculativeBranch(model_name="slow", output="same length text", latency_ms=200),
    ]
    rep = L.Tournament().run(branches)
    check("equal length -> latency tiebreak picks fast",
          rep.winner.model_name == "fast", f"got {rep.winner.model_name}")


def test_tournament_empty_returns_no_winner():
    rep = L.Tournament().run([])
    check("empty bracket -> no winner", rep.winner is None)
    check("empty bracket -> 0 standings", rep.standings == [])


def test_tournament_custom_judge():
    # Judge that prefers shorter outputs (anti-default).
    def judge(a, b):
        la, lb = len(a.output or ""), len(b.output or "")
        return 1 if la < lb else (-1 if la > lb else 0)
    branches = [
        L.SpeculativeBranch(model_name="short",  output="hi",          latency_ms=50),
        L.SpeculativeBranch(model_name="medium", output="hello world", latency_ms=50),
    ]
    rep = L.Tournament(judge_fn=judge).run(branches)
    check("custom judge picks shortest", rep.winner.model_name == "short")


# ---------- A8 Speculative Decoder ----------
def test_speculative_decoder_accept_all():
    sd = L.SpeculativeDecoder(verify_fn=lambda prefix, tok: True)
    out, rate = sd.decode("Once upon ", ["a ", "time", "."])
    check("accept-all yields full continuation",
          out == "Once upon a time.", f"got {out!r}")
    check("acceptance rate = 1.0", rate == 1.0, f"got {rate}")


def test_speculative_decoder_partial_acceptance():
    # Accept first two tokens, reject the third.
    state = {"i": 0}
    def verify(prefix, tok):
        state["i"] += 1
        return state["i"] <= 2
    sd = L.SpeculativeDecoder(verify_fn=verify)
    out, rate = sd.decode("start ", ["A", "B", "C", "D"])
    check("decoding stops at first rejection",
          out == "start AB", f"got {out!r}")
    check("ledger records 3 steps (2 accepted, 1 rejected, then break)",
          len(sd.ledger) == 3, f"got {len(sd.ledger)}")
    check("acceptance rate = 2/3",
          abs(rate - 2/3) < 1e-6, f"got {rate}")


def test_speculative_decoder_acceptance_rate_empty():
    sd = L.SpeculativeDecoder()
    check("no steps -> rate 0", sd.acceptance_rate() == 0.0)


# ---------- A12 Prompt Evolution ----------
def test_prompt_evolution_seed_dedupe():
    t = _tmp()
    try:
        eng = L.PromptEvolutionEngine(t/"pe.json")
        v1 = eng.seed("fast_mentor", "Be brief.")
        v2 = eng.seed("fast_mentor", "Be brief.")
        check("seed dedupes by text", v1 is v2)
        check("population has 1 variant",
              len(eng.populations["fast_mentor"]) == 1)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_prompt_evolution_record_outcome_updates_score():
    t = _tmp()
    try:
        eng = L.PromptEvolutionEngine(t/"pe.json")
        eng.seed("fast_mentor", "Always be brief and warm.")
        eng.record_outcome("fast_mentor", "Always be brief and warm.", True)
        eng.record_outcome("fast_mentor", "Always be brief and warm.", False)
        v = eng.best("fast_mentor")
        check("score = 0.5 after 1W 1L", abs(v.score - 0.5) < 1e-6, f"got {v.score}")
        check("samples = 2", v.samples == 2)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_prompt_evolution_mutation_produces_variant():
    base = "Always be brief and warm with the user."
    mutated = L.PromptEvolutionEngine._mutate(base)
    check("mutation differs from base", mutated != base, f"base={base!r} mut={mutated!r}")
    check("mutation preserves intent length-wise",
          0.6 * len(base) <= len(mutated) <= 2.0 * len(base),
          f"base_len={len(base)} mut_len={len(mutated)}")


def test_prompt_evolution_evolve_keeps_elite_and_fills_population():
    t = _tmp()
    try:
        eng = L.PromptEvolutionEngine(t/"pe.json",
                                       population_size=6, elite_keep=2)
        # Seed 4 variants with different scores.
        prompts = [
            "Always be brief and warm.",
            "Never repeat yourself.",
            "Be concise and brief, must respond directly.",
            "Should always sound warm and brief.",
        ]
        for i, p in enumerate(prompts):
            eng.seed("fast_mentor", p)
            # Give variants different observed performance.
            for _ in range(3):
                eng.record_outcome("fast_mentor", p, success=(i < 2))
        pop = eng.evolve("fast_mentor")
        check("population in [elite_keep+1, population_size]",
              3 <= len(pop) <= 6, f"got {len(pop)}")
        check("population strictly bigger than elite alone",
              len(pop) > 2, f"got {len(pop)}")
        elite_texts = [pop[i].text for i in range(2)]
        check("top-scoring prompts kept as elite",
              all(p in prompts[:2] for p in elite_texts),
              f"elite={elite_texts}")
        gens = sorted(set(v.generation for v in pop))
        check("new generation present in population",
              len(gens) >= 2, f"generations={gens}")
    finally: shutil.rmtree(t, ignore_errors=True)


def test_prompt_evolution_roundtrip():
    t = _tmp()
    try:
        eng = L.PromptEvolutionEngine(t/"pe.json")
        eng.seed("fast_mentor", "Be warm.")
        eng.record_outcome("fast_mentor", "Be warm.", True)
        eng.save()
        eng2 = L.PromptEvolutionEngine(t/"pe.json").load()
        check("evolution state round-trips",
              "fast_mentor" in eng2.populations
              and eng2.populations["fast_mentor"][0].score == 1.0)
    finally: shutil.rmtree(t, ignore_errors=True)


def test_no_regression():
    reg = L.AgentFactoryRegistry().registry
    p   = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_tournament_winner_by_wins,
        test_tournament_tie_breaks_by_latency,
        test_tournament_empty_returns_no_winner,
        test_tournament_custom_judge,
        test_speculative_decoder_accept_all,
        test_speculative_decoder_partial_acceptance,
        test_speculative_decoder_acceptance_rate_empty,
        test_prompt_evolution_seed_dedupe,
        test_prompt_evolution_record_outcome_updates_score,
        test_prompt_evolution_mutation_produces_variant,
        test_prompt_evolution_evolve_keeps_elite_and_fills_population,
        test_prompt_evolution_roundtrip,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Phase 3 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
