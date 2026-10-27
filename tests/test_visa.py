"""The visa list (visa.py): jobs in the EU and UK, kept apart, each with quoted evidence it sponsors.

The sentences are real ones from Arbeitnow and Hacker News postings (2026-10-13), shortened.
"""

import pytest

from jobhunter.classify import classify
from jobhunter.extract import enrich
from jobhunter.models import HYBRID, ONSITE, REJECTED, REMOTE, SHORTLISTED, VISA_LIST
from jobhunter.sponsors import Registers, Sponsor
from jobhunter.visa import read_posting

from .conftest import NOW, make_job


def _classify(filters, **overrides):
    overrides.setdefault("remote_status", ONSITE)
    job = make_job(**overrides)
    enrich(job)
    return classify(job, filters, NOW)


@pytest.fixture
def listed(filters):
    """The UK and NL lists, with a few real rows."""
    registers = Registers.from_rows("uk", [
        Sponsor("uk", "Monzo Bank Ltd", "London", "Worker (A rating), Skilled Worker"),
        Sponsor("uk", "Cursor Ltd", "Lincoln", "Worker (A rating), Skilled Worker"),
        Sponsor("uk", "Roofoods Ltd t/a Deliveroo", "London", "Worker (A rating), Skilled Worker"),
    ])
    Registers.from_rows("nl", [Sponsor("nl", "Picnic International B.V.", "", "KvK 61510084")], into=registers)
    filters.visa.registers = registers
    return filters


def test_a_visa_offer_puts_the_job_on_the_visa_list(filters):
    text = "We build APIs with Python.\n- Competitive relocation packages and visa sponsorship where necessary for expats."
    result = _classify(filters, allowed_locations=["Amsterdam, Netherlands"], description=text)
    assert result.status == VISA_LIST and result.eligibility.code == "visa_offered"
    assert result.eligibility.reasons[0] == (
        'On-site in "Amsterdam, Netherlands", the Netherlands; the posting offers a visa: '
        '"- Competitive relocation packages and visa sponsorship where necessary for expats."')


def test_a_401k_does_not_drop_a_job_that_sponsors_the_move(filters):
    """Roku Cambridge lists every country's benefits; a remote job with a 401(k) is still rejected."""
    text = ("We build APIs with Python.\n- Visa sponsorship available.\n"
            "- Medical, dental, and retirement options (401(k)/pension).")
    result = _classify(filters, allowed_locations=["London, United Kingdom"], description=text)
    assert result.status == VISA_LIST
    remote = _classify(filters, remote_status=REMOTE, allowed_locations=["Worldwide"], description=text)
    assert remote.status == REJECTED and remote.reject_code == "us_benefits"


@pytest.mark.parametrize("sentence", [
    "We sponsor visas for the right candidate.",
    "Surfly can provide or transfer Dutch visa sponsorship.",
    "Visa and relocation support",
    "London-based, in-person work, with UK Skilled Worker visa sponsorship and support for Global Talent applications.",
    "Relocation – you're ready to work onsite in Munich (we support visa)",
    "Right to work: We can sponsor visas for eligible candidates",
    "Comprehensive relocation support including flights, shipping and visas.",
    "We offer UK work permits and help with relocation.",
    # A clause about something else does not turn an offer into a refusal.
    "Visa sponsorship available (including transfer of Dutch visa; no relocation support)",
])
def test_offers_in_the_words_companies_use(sentence):
    assert read_posting(f"Python and FastAPI.\n{sentence}").offers == [sentence]


@pytest.mark.parametrize("sentence", [
    "WE CANNOT PROVIDE VISA SPONSORSHIP",
    "Permanent right to work in the UK is required; Socure does not provide visa sponsorship for this role.",
    "Unfortunately, WeTravel is not able to offer visa sponsorship or relocation assistance at this time.",
    "No visa sponsor available, No remote options available.",
    "Relocation and/or Visa are not supported for this role",
    "To be considered for this role, you'll need to have the independent right to work in the UK, as we're "
    "unfortunately unable to provide sponsorship at this time.",
])
def test_refusals_reject_the_job_quoted(filters, sentence):
    result = _classify(filters, allowed_locations=["London, United Kingdom"], description=f"Python APIs.\n{sentence}")
    assert result.status == REJECTED and result.reject_code == "no_sponsor"
    assert result.reject_reason == f'Does not sponsor visas: "{sentence}"'


@pytest.mark.parametrize("sentence", [
    "Executive sponsors and company-sponsored lunches.",
    "Join a team of ex-Netflix, Visa, Microsoft veterans.",
    "Scheme compliance (Visa/Mastercard).",
    "We can't guarantee visa approvals, however.",
])
def test_sponsorship_and_visa_in_other_senses_are_ignored(sentence):
    found = read_posting(sentence)
    assert not found.offers and not found.refusals


def test_a_right_to_work_alone_rejects_and_next_to_an_offer_is_a_note(filters):
    permit = "- Applicants must have the right to work in Germany at the time of application."
    alone = _classify(filters, allowed_locations=["Munich, Germany"], description=f"Python.\n{permit}")
    assert alone.reject_code == "no_sponsor"
    assert alone.reject_reason == f'Wants a right to work you would need a visa for: "{permit}"'

    offer = "We can sponsor visas to Germany; for any other country, you need to have existing right to work."
    both = _classify(filters, allowed_locations=["Germany"], description=f"Python.\n{offer}\n{permit}")
    assert both.status == VISA_LIST
    assert both.eligibility.reasons[1] == f'But it also says, ask about it: "{permit}"'
    # "or eligible for sponsorship" asks for nothing.
    either = "• Legally authorized to work in the Netherlands, or eligible for sponsorship"
    assert read_posting(either).permits == []


@pytest.mark.parametrize("sentence", [
    "- Sole British National",
    "- Eligibility: must be a UK national",
    "We can only consider applications from UK nationals (including dual nationals who hold British citizenship).",
    "We require applicants to hold a UK passport and 5 years of continuous UK residency.",
    "- British Passport or ILR",
])
def test_a_british_nationality_rejects_even_at_a_listed_sponsor(listed, sentence):
    """Palantir's UK Government roles (2026-10-21): on the register, but a visa cannot make you British."""
    listed.visa.registers = Registers.from_rows("uk", [
        Sponsor("uk", "Palantir Technologies UK Limited", "London", "Worker (A rating), Skilled Worker")])
    result = _classify(listed, company="Palantir", allowed_locations=["London, United Kingdom"],
                       description=f"Python.\n{sentence}")
    assert result.reject_code == "no_sponsor"
    assert result.reject_reason == f'Wants a right to work you would need a visa for: "{sentence}"'


@pytest.mark.parametrize("sentence", [
    "This role requires you to obtain and maintain the appropriate level of UK national security clearance.",
    "A British passport is a bonus.",
    "We support European and UK citizens with accommodation & travel arrangements.",
])
def test_british_in_other_senses_asks_for_nothing(sentence):
    assert read_posting(sentence).permits == []


def test_an_offer_and_a_refusal_together_list_the_job_with_the_refusal_to_ask_about(filters):
    text = ("Visa sponsorship: We do sponsor visas!\n"
            "However, we aren't able to successfully sponsor visas for every role and every candidate.")
    result = _classify(filters, allowed_locations=["Munich, Germany"], description=text)
    assert result.status == VISA_LIST and result.eligibility.code == "visa_offered"
    assert result.eligibility.reasons[1].startswith("But it also says, ask about it: \"However, we aren't able")


def test_relocation_help_without_a_visa_is_listed_as_weaker(filters):
    text = "Python.\nFor internationals: all-in relocation package and Dutch classes"
    result = _classify(filters, allowed_locations=["Amsterdam, Netherlands"], description=text)
    assert result.status == VISA_LIST and result.eligibility.code == "relocation_offered"
    assert "offers help moving, not a visa by name (ask)" in result.eligibility.reasons[0]
    # "No relocation support" offers nothing, and neither does a list of perks that "may include" it.
    assert read_posting("We offer no relocation support.").relocation == []
    assert read_posting("Benefits vary by country and may include healthcare coverage, parental leave, "
                        "relocation support, wellness programs.").relocation == []


def test_nothing_about_visas_rejects_with_what_was_checked(filters):
    berlin = _classify(filters, allowed_locations=["Berlin, Germany"])
    assert berlin.reject_code == "no_visa_evidence"
    assert berlin.reject_reason == ('On-site in "Berlin, Germany", Germany: the posting does not offer a visa, '
                                    "and Germany keeps no sponsor list")
    london = _classify(filters, allowed_locations=["London"])
    assert london.reject_reason.endswith("and the UK register of licensed sponsors is not downloaded "
                                         "(jobhunter sponsors --update)")


def test_a_company_on_the_sponsor_list_is_listed_with_its_row(listed):
    result = _classify(listed, company="Monzo", allowed_locations=["London, UK"])
    assert result.status == VISA_LIST and result.eligibility.code == "visa_register"
    assert result.eligibility.reasons[0] == (
        'On-site in "London, UK", the UK; the company is on the UK register of licensed sponsors: '
        '"Monzo Bank Ltd, London, Worker (A rating), Skilled Worker". The posting does not mention visas: ask')
    deliveroo = _classify(listed, company="Deliveroo", allowed_locations=["London"])
    assert "Roofoods Ltd t/a Deliveroo" in deliveroo.eligibility.reasons[0]
    picnic = _classify(listed, company="Picnic", allowed_locations=["Amsterdam"])
    assert picnic.eligibility.code == "visa_register" and '"Picnic International B.V., KvK 61510084"' in \
        picnic.eligibility.reasons[0]


def test_a_one_word_name_in_another_town_is_not_the_same_company(listed):
    result = _classify(listed, company="Cursor", allowed_locations=["London"])
    assert result.reject_code == "no_visa_evidence"
    assert "Cursor is not on the UK register of licensed sponsors" in result.reject_reason
    # Each list only counts for its own country.
    assert _classify(listed, company="Monzo", allowed_locations=["Berlin"]).reject_code == "no_visa_evidence"


def test_the_posting_wins_over_the_sponsor_list(listed):
    text = "Python.\nPlease note, we're unable to provide visa sponsorship for this role."
    result = _classify(listed, company="Monzo", allowed_locations=["London"], description=text)
    assert result.reject_code == "no_sponsor"


@pytest.mark.parametrize("sentence", [
    "- You speak German at C1 level or better and English fluently.",
    "Fluency in Dutch required",
    "Excellent German and English.",
    "- German language skills at B2 level or above",
    "Verhandlungssichere Deutsch- & Englischkenntnisse",
])
def test_a_language_you_dont_speak_rejects(filters, sentence):
    result = _classify(filters, allowed_locations=["Berlin, Germany"],
                       description=f"We offer visa sponsorship.\n{sentence}")
    assert result.reject_code == "language_required"
    assert result.reject_reason == f'Asks for a language your profile does not list: "{sentence}"'


@pytest.mark.parametrize("sentence", [
    "German is a plus.",
    "Communication: Excellent oral and written communication in Dutch or English (Business English C1 level).",
    "We have a strong presence in the German market.",
])
def test_a_language_that_is_optional_does_not(filters, sentence):
    result = _classify(filters, allowed_locations=["Berlin, Germany"],
                       description=f"We offer visa sponsorship.\n{sentence}")
    assert result.status == VISA_LIST


def test_a_posting_written_in_german_is_rejected(filters):
    text = ("Über uns\nWir sind ein junges Team und suchen dich für die Weiterentwicklung unserer Plattform. "
            "Du arbeitest mit Python und FastAPI und bist Teil eines Teams, das Verantwortung übernimmt. "
            "Wir bieten dir flexible Arbeitszeiten, ein modernes Büro in Berlin und die Möglichkeit, eigene Ideen "
            "einzubringen. Bei uns wirst du von Anfang an Teil der Produktentwicklung sein und mit uns wachsen.")
    result = _classify(filters, allowed_locations=["Berlin, Germany"], description=text)
    assert result.reject_code == "language_required"
    assert result.reject_reason == 'Written in German: "Über uns"'


def test_a_hacker_news_visa_header(filters):
    offer = _classify(filters, source="hackernews", company="Stream", allowed_locations=["Amsterdam"],
                      description="Stream | Backend Engineer | Amsterdam | ONSITE | VISA\nWe build chat APIs in Python.")
    assert offer.status == VISA_LIST
    assert offer.eligibility.reasons[0].endswith('the posting offers a visa: "VISA (Hacker News header)"')
    refusal = _classify(filters, source="hackernews", company="motan", allowed_locations=["Berlin, Germany"],
                        description="motan | Python Developer | Berlin, Germany | NO VISA (EU work authorisation "
                                    "required)\nPython.")
    assert refusal.reject_code == "no_sponsor"
    # The company field is the company, even when it is Visa.
    visa_inc = _classify(filters, source="hackernews", company="Visa", allowed_locations=["London"],
                         description="Visa | Backend Engineer | London | ONSITE\nPython.")
    assert visa_inc.reject_code == "no_visa_evidence"


def test_places_elsewhere_with_the_same_name_are_not_abroad(filters):
    for place in ("Dublin, OH", "London, Ontario, Canada", "Cambridge, MA", "Rome, GA"):
        result = _classify(filters, allowed_locations=[place])
        assert result.reject_code == "not_remote", place
    # DE is Germany, not Delaware.
    assert filters.visa.place_in(["Berlin, DE"])[1].code == "de"


def test_remote_for_people_living_there_needs_a_visa_too(filters):
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["United Kingdom"],
                       description="Python.\nUK visa sponsorship is available.")
    assert result.status == VISA_LIST
    assert result.eligibility.reasons[0].startswith('Remote, for people living in "United Kingdom", the UK;')
    # A region that includes Lebanon stays a remote job open to Lebanon.
    emea = _classify(filters, remote_status=REMOTE, allowed_locations=["EMEA", "London"])
    assert emea.status == SHORTLISTED and emea.eligibility.code == "region_ok"


def test_a_remote_job_open_to_lebanon_stays_a_remote_job(filters):
    # From the stored jobs (2026-10-13): these were shortlisted before the visa list and must stay so.
    tz = _classify(filters, source="hackernews", remote_status="unknown", company="OpenSanctions",
                   allowed_locations=["Berlin, Germany / REMOTE (CET ±3 preferred)"])
    assert tz.status == SHORTLISTED and tz.eligibility.verdict != "visa_sponsor"
    prefer = _classify(filters, remote_status=REMOTE, allowed_locations=["REMOTE (preferred Spain, UK, Poland, Romania)"],
                       description="Python.\nNo visa sponsorship/relocation.")
    assert prefer.status != REJECTED


def test_new_south_wales_is_not_the_uk(filters):
    result = _classify(filters, remote_status=REMOTE, allowed_locations=["New South Wales, Australia", "Remote"])
    assert result.reject_code == "location_restricted"


def test_a_remote_role_for_residents_needs_the_posting_to_offer_a_visa(listed):
    result = _classify(listed, remote_status=REMOTE, company="Monzo", allowed_locations=["Remote (UK)"])
    assert result.reject_code == "no_visa_evidence"
    assert result.reject_reason.endswith("and a remote role for people living there rarely comes with one")


def test_gulf_jobs_are_unchanged(filters):
    result = _classify(filters, remote_status=HYBRID, allowed_locations=["Dubai"])
    assert result.status == SHORTLISTED and result.eligibility.code == "relocation"


def test_the_visa_list_keeps_a_job_without_a_posting_date_with_a_note(filters):
    result = _classify(filters, allowed_locations=["London"], posted_at=None,
                       description="Python.\nVisa sponsorship is available.")
    assert result.status == VISA_LIST
    assert result.relevance.reasons[-1] == "No posting date, so its age is unknown"


def test_title_and_agency_rules_still_come_first(filters):
    text = "Python.\nVisa sponsorship is available."
    assert _classify(filters, title="Account Executive", allowed_locations=["London"],
                     description=text).reject_code == "title_not_target"
    assert _classify(filters, company="True Talent Solutions Partners", allowed_locations=["London"],
                     description=text).reject_code == "agency"


def test_the_visa_list_has_its_own_report_section(tmp_path, filters):
    from jobhunter.report import write_report
    from jobhunter.store import JobStore

    from .conftest import store_job

    store = JobStore(":memory:")
    store_job(store, filters)  # remote, open worldwide: shortlisted
    visa_id = store_job(store, filters, source_job_id="2", company="Wheely", remote_status=ONSITE,
                        allowed_locations=["London"],
                        description="Python.\n- Relocation support, including visa sponsorship and allowance")
    assert visa_id in {r["id"] for r in store.unreported()}
    store.set_report_date([r["id"] for r in store.unreported()], "2026-09-25")
    text = write_report(store, tmp_path, "2026-09-25", None, NOW).read_text()
    assert "1 shortlisted · 1 on the visa list · 0 rejected" in text
    section = text.split("## Visa list (1)")[1].split("## Rejected")[0]
    assert "Wheely" in section and '- **Visa:** visa_sponsor — On-site in "London", the UK;' in section
    assert "Wheely" not in text.split("## Visa list")[0]
    assert store.unreported() == []


def test_relocation_to_another_country_does_not_count(filters):
    text = "Python.\nLocation: Cyprus — Onsite (employment contract with relocation support)"
    result = _classify(filters, title="Senior Backend Python Engineer - Relocation to Cyprus",
                       allowed_locations=["Netherlands"], description=text)
    assert result.reject_code == "no_visa_evidence"


def test_a_source_without_posting_text_says_so(listed):
    result = _classify(listed, source="getro", company="Monzo", allowed_locations=["London, UK"], description="")
    assert result.status == VISA_LIST
    assert result.eligibility.reasons[0].endswith("This source gives no posting text: read it and ask")
