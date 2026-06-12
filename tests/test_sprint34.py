"""Sprint 34 - belief retrieval embedding fix tests."""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "latticed"))
import latticed as L  # noqa: E402

results: list[tuple[str, str, str]] = []
def check(n, c, d=""): results.append((n, "PASS" if c else "FAIL", d))


# ---------- fact normalization ----------
def test_normalize_the_user_goes():
    out = L._normalize_fact_for_embedding("The user goes hiking almost every Saturday morning.")
    check("'The user goes' -> 'I go'",
          out == "I go hiking almost every Saturday morning.", f"got {out!r}")


def test_normalize_user_likes():
    out = L._normalize_fact_for_embedding("User likes Thai food.")
    check("'User likes' -> 'I like'", out == "I like Thai food.", f"got {out!r}")


def test_normalize_users_possessive():
    out = L._normalize_fact_for_embedding("The user's favorite season is fall.")
    check("possessive prefix stripped to 'I ...'",
          out == "I favorite season is fall.", f"got {out!r}")


def test_normalize_unknown_verb_kept():
    out = L._normalize_fact_for_embedding("The user hikes every weekend.")
    check("unmapped verb kept, pronoun still fixed",
          out == "I hikes every weekend.", f"got {out!r}")


def test_normalize_first_person_untouched():
    fact = "I go hiking almost every Saturday morning."
    check("already first-person -> unchanged",
          L._normalize_fact_for_embedding(fact) == fact)


def test_normalize_non_user_subject_untouched():
    fact = "The market closed higher on Friday."
    check("non-user subject -> unchanged",
          L._normalize_fact_for_embedding(fact) == fact)


def test_normalize_empty():
    check("empty -> empty", L._normalize_fact_for_embedding("") == "")


# ---------- query expansion ----------
def test_expand_fun_query():
    q = "What do I like to do for fun?"
    out = L._expand_self_query(q)
    check("fun query expanded", out != q and "hobbies" in out, f"got {out!r}")


def test_expand_hobby_query():
    q = "What are my hobbies?"
    out = L._expand_self_query(q)
    check("hobby query expanded", "leisure" in out, f"got {out!r}")


def test_no_expand_financial_query():
    q = "What is my monthly rent?"
    out = L._expand_self_query(q)
    check("financial self-query NOT expanded (no preference terms)",
          out == q, f"got {out!r}")


def test_no_expand_third_party_query():
    q = "What do people like to do for fun?"
    out = L._expand_self_query(q)
    check("non-self query NOT expanded", out == q, f"got {out!r}")


def test_no_expand_empty():
    check("empty query unchanged", L._expand_self_query("") == "")


# ---------- encoder-gated integration: the actual eval-14 scenario ----------
def test_eval14_scenario_clears_threshold():
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        check("eval-14 integration (SKIPPED - no sentence_transformers)", True,
              "encoder not installed")
        return
    m = SentenceTransformer("all-MiniLM-L6-v2")

    def sim(a, b):
        ea, eb = m.encode(a, convert_to_numpy=True), m.encode(b, convert_to_numpy=True)
        return float(np.dot(ea, eb) / (np.linalg.norm(ea) * np.linalg.norm(eb)))

    query = "What do I like to do for fun?"
    expanded = L._expand_self_query(query)
    stored_facts = [
        "The user goes hiking almost every Saturday morning.",
        "User goes hiking on Saturday mornings.",
        "I go hiking almost every Saturday morning.",
    ]
    for fact in stored_facts:
        norm = L._normalize_fact_for_embedding(fact)
        best = max(sim(query, norm), sim(expanded, norm))
        check(f"hiking fact clears 0.30 threshold ({fact[:30]}...)",
              best >= L.BELIEF_RELEVANCE_THRESHOLD,
              f"best={best:.3f}")
    # False-positive control: unrelated fact must STAY filtered.
    ctrl = "The user's monthly rent is $1,800."
    ctrl_norm = L._normalize_fact_for_embedding(ctrl)
    ctrl_best = max(sim(query, ctrl_norm), sim(expanded, ctrl_norm))
    check("control (rent) fact stays below threshold",
          ctrl_best < L.BELIEF_RELEVANCE_THRESHOLD, f"best={ctrl_best:.3f}")


# ---------- regression ----------
def test_no_regression():
    L.install_encrypted_persistence(None)
    reg = L.AgentFactoryRegistry().registry
    p = L.hardware_profile_detect(force_tier="minimal_gpu")
    rep = L.validate_profile_against_agents(p, reg, strict=True)
    check("MINIMAL_GPU validates", rep.valid)
    check("agent count = 12", len(reg) == 12)


def main():
    tests = [
        test_normalize_the_user_goes,
        test_normalize_user_likes,
        test_normalize_users_possessive,
        test_normalize_unknown_verb_kept,
        test_normalize_first_person_untouched,
        test_normalize_non_user_subject_untouched,
        test_normalize_empty,
        test_expand_fun_query,
        test_expand_hobby_query,
        test_no_expand_financial_query,
        test_no_expand_third_party_query,
        test_no_expand_empty,
        test_eval14_scenario_clears_threshold,
        test_no_regression,
    ]
    for tt in tests:
        try: tt()
        except Exception as e: results.append((tt.__name__, "FAIL", f"EXC {type(e).__name__}: {e}"))
    p = sum(1 for _, s, _ in results if s == "PASS")
    for n, s, d in results:
        print(("[OK]  " if s == "PASS" else "[XX]  ") + n + (f"   - {d}" if d else ""))
    print(f"\n{p}/{len(results)} Sprint 34 tests passed.")
    return 0 if p == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
