import pytest

from integrity.common import textnorm as tn


def span_text(quote, text):
    sp = tn.find_span(quote, text)
    return None if sp is None else text[sp[0]:sp[1]]


@pytest.mark.parametrize(
    "quote,text",
    [
        ("every man has a property in his own person", "every man has a property in his own person."),
        ("“the state of nature” is", "the \"state of nature\" is"),  # curly vs straight
        ("it’s power", "it's power"),
        ("power—not right", "power - not right"),
        ("power–not right", "power--not right"),
        ("happiness that", "happiness-that"),
        ("is power.", "is power ."),  # stray space before punctuation
        ("a priori reasoning", "à priori reasoning"),
        ("prima facie", "primâ facie"),
        ("Tiers Etat", "Tiers État"),
        ("caesar", "Cæsar"),
        ("Cæsar", "Caesar"),
        ("oeuvre", "œuvre"),
        ("permanence of the state", "the per manence of the state"),
        ("per manence", "permanence"),
        ("the state of nature", "the state of* nature"),
        ("café society", "café society"),  # composition differences
        ("αὐτός", "αὕτός"),  # Greek combining accents
        ("war and peace", "WAR & PEACE"),
        ("rock & roll", "rock and roll"),
    ],
)
def test_tolerated_hazards(quote, text):
    assert tn.find_span(quote, text) is not None


@pytest.mark.parametrize(
    "quote,text",
    [
        ("solitary, poor", "solitary, poore"),  # modernised last word: word-boundary rule
        ("poor", "poore"),
        ("WAR", "WARRE"),
        ("war", "the warre of all"),
        ("the cat sat", "the cat quietly sat"),  # dropped/inserted word
        ("the cat sat", "the sat"),
        ("shew mercy", "show mercy"),
        ("connexion", "connection"),
        ("ate the", "he plate the"),  # starts mid-word
    ],
)
def test_strict_on_letters(quote, text):
    assert tn.find_span(quote, text) is None


@pytest.mark.parametrize("quote", ["power ... right", "power … right", "a...b"])
def test_ellipsis_rejected_even_if_text_contains_it(quote):
    assert tn.find_span(quote, quote) is None
    assert tn.find_matches(quote, "power ... right a...b") == []


def test_span_is_original_text_and_first_match():
    text = "He said: \"state of* nature\" twice; state of nature."
    assert span_text("state of nature", text) == "state of* nature"
    assert tn.find_span("state of nature", text) == (9 + 1, 9 + 1 + len("state of* nature"))
    assert tn.count_matches("state of nature", text) == 2


def test_invalid_first_match_skipped_valid_counted():
    text = "poore men, and poor men"
    # 'poor men' does not match 'poore men'; the second is valid
    assert tn.count_matches("poor men", text) == 1
    assert span_text("poor men", text) == "poor men"


def test_overlapping_occurrences():
    assert tn.count_matches("aa", "aa aa") == 2
    assert tn.count_matches("a a", "a a a") == 2


def test_empty_quote_and_trailing_combining():
    assert tn.find_span("", "abc") is None
    assert tn.find_span("!!!", "abc") is None
    text = "voila café now"
    assert span_text("cafe", text) == "café"


def test_skeleton_and_word_count():
    assert tn.skeleton("Café æon, WAR & peace! 42") == "cafeaeonwarandpeace42"
    assert tn.skeleton("ß") == "ss"
    assert tn.word_count("a  b -- c, — d") == 4
    assert tn.word_count("") == 0
    assert tn.TEXTNORM_VERSION == 1
