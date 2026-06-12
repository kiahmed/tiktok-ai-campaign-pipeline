"""Unit tests for HeyGen auto-selection of avatar + voice (pure ranking logic)."""
from app.providers.heygen import HeyGenVideoProvider as H


AVATARS = [
    {"avatar_id": "a_fem_free", "gender": "female", "premium": False, "default_voice_id": "vf"},
    {"avatar_id": "a_male_prem", "gender": "male", "premium": True, "default_voice_id": "vmp"},
    {"avatar_id": "a_male_free", "gender": "male", "premium": False, "default_voice_id": "vmf"},
]
VOICES = [
    {"voice_id": "v_es_m", "gender": "male", "language": "Spanish"},
    {"voice_id": "v_en_f", "gender": "female", "language": "English"},
    {"voice_id": "v_en_m", "gender": "male", "language": "English"},
]


def test_avatar_prefers_gender_then_free():
    # male preference -> the free male avatar wins over the premium male and female
    assert H._choose_avatar(AVATARS, "male")["avatar_id"] == "a_male_free"


def test_voice_prefers_gender_then_english():
    assert H._choose_voice(VOICES, "male")["voice_id"] == "v_en_m"


def test_no_gender_bias_still_picks_english_voice():
    assert H._choose_voice(VOICES, "")["voice_id"] == "v_en_f"


def test_empty_catalog_raises():
    import pytest
    from app.core.exceptions import VideoGenerationError

    with pytest.raises(VideoGenerationError):
        H._choose_avatar([], "male")
    with pytest.raises(VideoGenerationError):
        H._choose_voice([], "male")


def _script(text="My hairline killed my confidence. This oil fixed it. Link in bio.", vp=""):
    from app.core.entities import ScriptResult

    return ScriptResult(text=text, provider="t", model="m", visual_prompt=vp)


class _IdxRng:
    """Deterministic stand-in for random.Random: choice() returns a fixed index."""

    def __init__(self, i: int = 0) -> None:
        self.i = i

    def choice(self, seq):
        return seq[self.i % len(seq)]


def test_voice_follows_avatar_default_and_catalog_cached():
    """No LLM => random pick among the pool; voice = that avatar's default_voice_id."""
    g = H(api_key="k", prefer_gender="male", smart_avatar=False, rng=_IdxRng(0))
    calls = []

    def fake_list(path):
        calls.append(path)
        return {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}

    g._list = fake_list
    avatar_id, voice_id = g._resolve(_script())
    # free male avatar, and its OWN default voice (so /v2/voices is never hit)
    assert avatar_id == "a_male_free"
    assert voice_id == "vmf"
    assert calls == ["/v2/avatars"]

    # same script => memoised (no extra catalog calls)
    g._resolve(_script())
    assert calls == ["/v2/avatars"]


def test_llm_casts_avatar_per_script():
    """The LLM picks the avatar; the voice still follows that avatar."""
    class FakeLLM:
        name = "fake"

        def __init__(self):
            self.seen = []

        def complete(self, system, user):
            self.seen.append(user)
            return "a_male_prem"  # LLM prefers the premium male for this script

    llm = FakeLLM()
    g = H(api_key="k", prefer_gender="male", llm=llm, smart_avatar=True)
    g._list = lambda path: {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}

    avatar_id, voice_id = g._resolve(_script(vp="a rugged 40-year-old man"))
    assert avatar_id == "a_male_prem"      # the LLM's choice won
    assert voice_id == "vmp"               # voice follows that avatar's default
    assert "rugged 40-year-old man" in llm.seen[0]  # script notes were sent


def test_gender_comes_from_profile_narrator():
    """No HEYGEN_PREFER_GENDER set — gender is taken from directives.narrator."""
    from app.core.entities.profile import CreativeDirectives

    g = H(api_key="k", smart_avatar=False, rng=_IdxRng(0))  # no prefer_gender configured
    g._list = lambda path: {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}

    male = g._resolve(_script(), CreativeDirectives(narrator="male"))
    assert male[0] in {"a_male_free", "a_male_prem"}   # narrator=male -> a male avatar
    female = g._resolve(_script("different script"), CreativeDirectives(narrator="female"))
    assert female[0] == "a_fem_free"  # narrator=female -> the only female avatar


def test_no_gender_anywhere_lets_llm_pick_any_gender():
    """No narrator and no config => LLM casts across all genders."""
    class FemaleLLM:
        name = "f"

        def complete(self, system, user):
            return "a_fem_free"

    g = H(api_key="k", llm=FemaleLLM(), smart_avatar=True)  # no prefer_gender, no narrator
    g._list = lambda path: {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}
    avatar_id, _ = g._resolve(_script())  # directives=None
    assert avatar_id == "a_fem_free"  # LLM freely chose a female from the script


def test_llm_bad_reply_falls_back_to_random_pool():
    class JunkLLM:
        name = "junk"

        def complete(self, system, user):
            return "I think any of them works!"  # no valid avatar_id

    g = H(api_key="k", prefer_gender="male", llm=JunkLLM(), smart_avatar=True, rng=_IdxRng(0))
    g._list = lambda path: {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}
    avatar_id, voice_id = g._resolve(_script())
    # falls back to a random male from the pool (idx 0 of the sorted pool)
    assert avatar_id == "a_male_free"
    assert voice_id == "vmf"


def test_random_pool_varies_the_presenter():
    """Different RNG => different male presenter (variety across videos)."""
    def make(rng):
        g = H(api_key="k", prefer_gender="male", smart_avatar=False, rng=rng)
        g._list = lambda path: {"avatars": AVATARS} if path == "/v2/avatars" else {"voices": VOICES}
        return g._resolve(_script())[0]

    assert make(_IdxRng(0)) == "a_male_free"   # first of the sorted male pool
    assert make(_IdxRng(1)) == "a_male_prem"   # second -> a DIFFERENT man


# Avatars WITHOUT a default voice (like HeyGen's /v2/avatars) => voice is random.
AVATARS_NO_VOICE = [
    {"avatar_id": "m1", "gender": "male", "premium": False},
    {"avatar_id": "m2", "gender": "male", "premium": False},
]


def test_voice_is_random_when_avatar_has_no_default():
    def make(rng):
        g = H(api_key="k", prefer_gender="male", smart_avatar=False, rng=rng)
        g._list = lambda p: {"avatars": AVATARS_NO_VOICE} if p == "/v2/avatars" else {"voices": VOICES}
        return g._resolve(_script())[1]   # voice_id

    # English male voices sorted: [v_en_m]; with only one english-male it's stable,
    # but the candidate pool prefers english then id, so different rng can vary it.
    v0 = make(_IdxRng(0))
    v1 = make(_IdxRng(1))
    assert v0 in {"v_en_m", "v_es_m"}      # a male voice was chosen
    assert v1 in {"v_en_m", "v_es_m"}
    # different indices select different voices from the male pool
    assert v0 != v1
