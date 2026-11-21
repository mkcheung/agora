import pytest

from integrity.common.settings import ConfigError, load_settings


def write(tmp_path, body, name="over.toml"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_defaults_load_and_match_plan(monkeypatch):
    monkeypatch.delenv("INTEGRITY_CONFIG")
    s = load_settings()
    assert s.models.drafter == "openai:gpt-4.1"
    assert s.checks.quote_min_words == 6 and s.checks.quote_max_words == 40
    assert len(s.strata) == 12 and s.strata[0].name == "locke-front-matter"
    assert s.strata[-1].paragraph_in == [7, 18, "76-79", 133, 139]
    assert len(s.eligibility.denylist) >= 2
    assert s.eligibility.denylist[0].locator_regex.startswith("^Book II")
    assert s.judge.prompts["coverage"] == "judge_coverage_v1"
    assert s.publish.holdout_percent == 15
    # project root is the repo root; data_dir hangs off it
    assert (s.project_root / "integrity").is_dir()
    assert s.data_dir == s.project_root / "integrity_data"


def test_per_author_overrides(monkeypatch):
    monkeypatch.delenv("INTEGRITY_CONFIG")
    s = load_settings()
    assert s.author_rules("John Stuart Mill")["min_chars"] == 800
    assert s.author_rules("Thomas Hobbes")["max_quoted_fraction"] == 0.5
    burke = s.author_rules("Edmund Burke")
    assert burke["quoted_text_is_other_speaker"] is True and burke["three_points_min_chars"] == 900
    locke = s.author_rules("John Locke")
    assert locke["min_chars"] == 600 and locke["quoted_text_is_other_speaker"] is False


def test_config_file_deep_merges(tmp_path, monkeypatch):
    p = write(tmp_path, '[build]\ndefault_count = 5\n[authors."John Locke"]\nmin_chars = 700\n')
    monkeypatch.setenv("INTEGRITY_CONFIG", str(p))
    s = load_settings()
    assert s.build.default_count == 5
    assert s.build.max_attempts_per_slot == 3  # untouched sibling key survives
    assert s.authors["John Stuart Mill"].min_chars == 800  # untouched sibling table survives
    assert s.authors["John Locke"].min_chars == 700


def test_arrays_of_tables_are_replaced(tmp_path, monkeypatch):
    p = write(tmp_path, '[[strata]]\nname = "only"\nwork_id = ["x"]\nweight = 1.0\n')
    monkeypatch.setenv("INTEGRITY_CONFIG", str(p))
    s = load_settings()
    assert [st.name for st in s.strata] == ["only"]


def test_env_beats_file_and_cli_beats_env(tmp_path, monkeypatch):
    p = write(tmp_path, "[build]\ndefault_count = 5\n")
    monkeypatch.setenv("INTEGRITY_CONFIG", str(p))
    monkeypatch.setenv("INTEGRITY_BUILD__DEFAULT_COUNT", "7")
    monkeypatch.setenv("INTEGRITY_QUIZ__STRICT", "true")
    monkeypatch.setenv("INTEGRITY_MODELS__JUDGE", "anthropic:x")
    s = load_settings()
    assert s.build.default_count == 7 and s.quiz.strict is True and s.models.judge == "anthropic:x"
    s = load_settings({"build": {"default_count": 9}})
    assert s.build.default_count == 9


def test_env_rejects_non_scalar_unknown_and_bad_values(monkeypatch):
    monkeypatch.setenv("INTEGRITY_ELIGIBILITY__CONTENT_TYPES", "prose")
    with pytest.raises(ConfigError, match="scalar"):
        load_settings()
    monkeypatch.delenv("INTEGRITY_ELIGIBILITY__CONTENT_TYPES")
    monkeypatch.setenv("INTEGRITY_BUILD__NOPE", "1")
    with pytest.raises(ConfigError):
        load_settings()
    monkeypatch.delenv("INTEGRITY_BUILD__NOPE")
    monkeypatch.setenv("INTEGRITY_BUILD__DEFAULT_COUNT", "many")
    with pytest.raises(ConfigError, match="bad value"):
        load_settings()


@pytest.mark.parametrize(
    "body",
    ["[build]\nbogus = 1\n", "[nosuchsection]\nx = 1\n", '[authors."A"]\nbogus = 1\n',
     "[[strata]]\nname='a'\nwork_id=['w']\nweight=1\nextra=2\n", "[models]\ntracing = 'maybe'\n"],
)
def test_unknown_keys_and_bad_values_error(tmp_path, monkeypatch, body):
    monkeypatch.setenv("INTEGRITY_CONFIG", str(write(tmp_path, body)))
    with pytest.raises(ConfigError):
        load_settings()


def test_missing_and_malformed_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INTEGRITY_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(ConfigError, match="not found"):
        load_settings()
    monkeypatch.setenv("INTEGRITY_CONFIG", str(write(tmp_path, "[build\n")))
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_settings()


def test_data_dir_from_test_config(data_dir):
    assert load_settings().data_dir == data_dir


def test_project_root_in_override_is_relative_to_that_file(tmp_path, monkeypatch):
    p = write(tmp_path, '[seams]\nproject_root = "sub"\n')
    monkeypatch.setenv("INTEGRITY_CONFIG", str(p))
    assert load_settings().project_root == (tmp_path / "sub").resolve()
