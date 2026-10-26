"""The fact check's building blocks. The email, the CV and the cover letter all lean on these, so their
behavior is pinned here: a change shows up as a failing test, not as a CV that lets a number through."""

from jobhunter.grounding import (
    capitalized_words, check_years, digits, fact_has, number_context, stem, unsupported_seniority, word_list,
)


def test_numbers_come_with_their_suffix_and_the_next_word():
    assert number_context("I lead a team of five engineers: 800+ concurrent jobs, 40% faster, 1,200 users.") == [
        ("5", "", "engineers"), ("800", "+", "concurrent"), ("40", "%", "faster"), ("1200", "", "users"),
    ]
    assert digits("Five engineers, twelve months") == "5 engineers, 12 months"


def test_a_number_matches_a_fact_only_next_to_the_same_word():
    fact = "Runs 800+ concurrent Python jobs over historical market data."
    assert fact_has("800", "jobs", fact) and fact_has("800", "job", fact)  # plural or not
    assert fact_has("800", None, fact)
    assert not fact_has("800", "data", fact)  # more than four words after the number
    assert not fact_has("900", "jobs", fact)
    assert not fact_has("5", "years", "Lead a team of 5 engineers.")


def test_names_are_capitalized_words_after_a_sentence_s_first():
    assert capitalized_words('I used Workato with AWS. Python runs it. "Kafka is new.') == ["Workato", "AWS"]


def test_words_and_stems():
    assert word_list("800+ AWS-Lambda, C#") == ["800", "aws", "lambda", "c"]
    assert (stem("jobs"), stem("aws"), stem("bus")) == ("job", "aws", "bus")


def test_years_never_above_the_profile_s_whole_years():
    assert check_years("3", "+", 3.3) is None
    assert check_years("4", "+", 3.3) == "claims 4+ years; the profile has about 3.3 years"
    assert check_years("2", "", None) == "claims 2 years; the profile has about no stated years"


def test_seniority_words_must_be_in_the_source():
    assert unsupported_seniority("Senior engineer and team lead", "Lead a team of 5 engineers") == ["senior"]
    assert unsupported_seniority("I led the team", "Lead a team") == []  # "led" is not a seniority word
    assert unsupported_seniority("a leader", "") == []  # whole words only
