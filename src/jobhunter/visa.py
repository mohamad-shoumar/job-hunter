"""The visa list: target roles in countries you would move to on a work visa (the EU and UK).

A separate list (status visa_list), not the shortlist: these jobs mean moving,
so they stay apart from the remote ones and get no automatic CV, cover letter
or contact lookup. A job gets on it only with evidence that the employer
sponsors visas, each quoted:

  visa_offered        the posting offers it: "We offer visa sponsorship and relocation support"
  visa_offered        a Hacker News header says "VISA" (the thread's convention)
  relocation_offered  it offers help moving, not a visa by name: "For internationals: all-in
                      relocation package". Weaker; the reason says to ask
  visa_register       the company is on that country's government sponsor list (sponsors.py)

Rejected, quoted:

  no_sponsor         the posting refuses ("We are unable to provide visa sponsorship"),
                     or asks for a right to work you don't have and offers nothing
  language_required  it asks for a language your profile does not list ("Fluent German (C1)"),
                     or is written in one
  no_visa_evidence   nothing says it sponsors

Found 2026-10-13 in real postings (docs/research/2026-10-13-eu-visa-sponsorship.md):
"sponsorship" alone is mostly about events and executives ("executive sponsors",
"company-sponsored lunches"), and "Visa" is also a company, so an offer needs
the visa words together. Each clause is judged alone, so "Visa sponsorship
available (no relocation support)" is an offer, not a refusal. When a posting
both offers and refuses ("We do sponsor visas!" ... "we aren't able to sponsor
visas for every role"), it is listed with the refusal as a note to ask about.

Never `unclear`: the AI check asks about remote hiring from Lebanon, the wrong
question here. Countries, places and languages are the "visa_list" section of
config/filters.json; the phrases are below, like the rules in eligibility.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import HYBRID, NOT_ELIGIBLE, ONSITE, REMOTE, VISA_SPONSOR, Assessment, Job
from .sponsors import LISTS, Registers
from .text import normalize_words

_NEG = (r"(?:no|not|never|unable|cannot|can't|can’t|won't|won’t|don't|don’t|doesn't|doesn’t|isn't|isn’t|aren't|"
        r"aren’t|without|unfortunately)")
_NEGATION = re.compile(rf"\b{_NEG}\b", re.I)
_SPONSOR_WORD = re.compile(r"\bsponsor(?:s|ed|ing|ship|ships)?\b", re.I)
# An offer: the visa words together, never "sponsorship" alone.
_OFFER = re.compile(
    r"\bvisas?\s+(?:sponsor(?:ship|s|ed|ing)?|support|assistance|services|help|application\s+support)\b"
    r"|\bsponsor(?:s|ing|ship\s+(?:for|of))?\s+(?:\w[\w-]*\s+){0,3}?(?:visas?|work\s+permits?)\b"  # "H-1B visas"
    r"|\bsupports?\s+(?:\w+\s+){0,2}?visas?\b"
    r"|\brelocation\s+(?:and|&|/|and/or)\s+visas?\b|\bvisas?\s+(?:and|&|/)\s+relocation\b"
    r"|\b(?:skilled\s+worker|blue\s+card|highly\s+skilled\s+migrant|kennismigrant|critical\s+skills|global\s+talent)"
    r"\s+(?:visa|permit|sponsorship)\b"
    r"|\bwork\s+permit\s+sponsorship\b"
    # "We offer UK work permits"
    r"|\b(?:offer|provide|arrange|handle|cover|sponsor)\w*\s+(?:\w+\s+){0,3}?(?:work\s+permits?|work\s+visas?)\b",
    re.I,
)
# "Relocation support including flights, shipping and visas": a list, so judged on the whole sentence.
_RELOCATION_WITH_VISA = re.compile(r"\brelocat\w*\b[^.]{0,80}?\bvisas?\b", re.I)
# Help moving, without the word visa. Weaker than an offer: the reason says so.
_RELOCATION = re.compile(
    r"\brelocation\s+(?:package|support|assistance|allowance|bonus|budget|help|benefits?|stipend|costs?)\b"
    r"|\b(?:help|support|assist)\w*\s+(?:you\s+)?(?:with\s+)?(?:your\s+)?relocat\w*"
    r"|\brelocation\s+(?:is\s+)?(?:provided|offered|covered|paid|available)\b"
    r"|\b(?:pay|cover)\s+(?:for\s+)?(?:your\s+)?relocation\b",
    re.I,
)
_MAYBE = re.compile(r"\bmay\s+include\b|\bvar(?:y|ies)\s+by\b", re.I)
# A refusal: a negation with "sponsor..." or with a visa being supported/provided/offered.
_VISA_HELP = re.compile(r"\bvisas?\b[^.;:]{0,40}\b(?:support|supported|provide|provided|offer|offered|available|assist)", re.I)
# Refusals the clause split would cut in two (Corgi, wolt; 2026-10-31): a field and its value,
# "Visa Sponsorship: Not available", and a list after one "unable", "unable to offer fully remote
# work, visa sponsorship, or relocation support". Not "Visa sponsorship available - no relocation
# support", and not "can't offer remote work, but we do sponsor visas".
_FIELD_REFUSAL = re.compile(
    r"\b(?:visas?|sponsorship|work\s+permits?)\b[^:.;]{0,25}?\s*[:–—-]\s*"
    r"(?:not\s+(?:available|offered|provided|possible|supported)\b|(?:unavailable|none|no|n/a)\s*(?:$|[.,;)]))",
    re.I,
)
_LIST_REFUSAL = re.compile(
    r"\b(?:unable|cannot|can't|can’t|not\s+able|won't|won’t|will\s+not|do\s+not|don't|don’t|does\s+not|doesn't|"
    r"doesn’t)\s+(?:to\s+)?(?:offer|provide|support|sponsor|give)\b"
    r"(?:(?!\b(?:but|however|although|though|while|whereas)\b)[^.;:!?]){0,100}?\b(?:visas?|sponsorship)\b",
    re.I,
)
# "... and visa sponsorship is available": the list ended, the visa is offered.
_OFFERED_AFTER = re.compile(r"[^,]*?\b(?:is|are)\s+(?:available|offered|provided|possible)\b", re.I)
# Help only with a visa you already hold (Wise: "For local candidates we are able to support transfer
# of visa sponsorship"). Not "can provide or transfer Dutch visa sponsorship", which offers one too.
_TRANSFER = re.compile(
    r"(?<!\bor\s)(?<!\band\s)(?<!/\s)(?<!/)\btransfer(?:s|ring)?\s+(?:of\s+)?(?:\w+\s+){0,2}?visas?(?:\s+sponsorship)?\b"
    r"|\bvisas?\s+transfers?\b|\btransfers?\s+only\b",
    re.I,
)
# A right to work you must already have. Alone it rejects; next to an offer it is a note.
_NEEDS_PERMIT = re.compile(
    r"\b(?:right|authori[sz]ed|authori[sz]ation|eligible|eligibility|entitled|permitted|permission)\s+to\s+work\s+"
    r"(?:in|within|for)\s+(?:the\s+)?(?:uk|u\.k\.|united\s+kingdom|britain|eu|e\.u\.|european\s+union|eea|europe|"
    r"netherlands|germany|ireland|spain|italy|finland)\b"
    r"|\bvalid\s+(?:work(?:ing)?\s+(?:permit|visa)|residence\s+permit)\b|\bexisting\s+right\s+to\s+work\b"
    r"|\b(?:eu|e\.u\.|eea)\s+(?:citizen(?:ship)?s?|passport|nationals?)\b|\b(?:pre-?)?settled\s+status\b"
    r"|\bindefinite\s+leave\s+to\s+remain\b"
    # A nationality, which no visa gives: "Sole British National" (Palantir), "must be a UK national".
    # Not "UK national security clearance" or "a British passport is a bonus".
    r"|\bsole\s+(?:british|uk)\s+nationals?\b"
    r"|\bmust\s+(?:be|hold)\s+(?:a\s+)?(?:british|uk|u\.k\.)\s+(?:nationals?|citizens?|citizenship|passport)\b"
    r"|\bonly\s+consider\s+(?:\w+\s+){0,2}?from\s+(?:british|uk)\s+(?:nationals|citizens)\b"
    r"|\b(?:hold|have)\s+a\s+(?:british|uk)\s+passport\b|\b(?:british|uk)\s+passport\s+or\s+ilr\b",
    re.I,
)
_HN_VISA = re.compile(r"(?<![A-Za-z])visa(?![A-Za-z])", re.I)
_CLAUSE_SPLIT = re.compile(r"[,;:()\[\]]|\s[–—-]\s")
# "German is a plus", and "in Dutch or English": not a requirement.
_SOFTENER = re.compile(r"\b(?:plus|nice\s+to\s+have|bonus|advantage\w*|preferred|helpful|beneficial|desirable|"
                       r"not\s+(?:required|necessary|needed|mandatory|a\s+requirement)|no\s+\w+\s+(?:required|needed)|"
                       r"(?:or|and/or)\s+english|english\s+(?:or|and/or))\b", re.I)

# Words that make up much of a posting written in that language, and rarely appear in English.
_FUNCTION_WORDS = {
    "german": {"und", "der", "das", "wir", "für", "fur", "mit", "ist", "nicht", "auf", "bei", "oder", "eine", "einen",
               "zu", "von", "den", "dem", "des", "als", "auch", "du", "dich", "deine", "dein", "unser", "unsere",
               "ihre", "sie", "uns", "werden", "sowie"},
    "dutch": {"en", "het", "van", "een", "wij", "je", "jouw", "voor", "met", "niet", "zijn", "ook", "bij", "naar",
              "ons", "onze", "wat", "deze", "jij", "heb", "hebt", "wordt"},
    "spanish": {"y", "el", "los", "las", "con", "para", "por", "una", "del", "nuestro", "nuestra", "que", "es",
                "se", "tu", "tus", "como", "más", "mas"},
    "italian": {"il", "di", "che", "per", "con", "una", "del", "della", "nostro", "nostra", "sei", "sono", "gli",
                "nel", "nella", "alla", "dei", "delle"},
    "finnish": {"ja", "on", "tai", "sekä", "seka", "meillä", "meilla", "sinulla", "olet", "kanssa", "että", "etta",
                "tämä", "tama", "jos", "myös", "myos"},
}
_WRITTEN_IN_SHARE = 0.12


@dataclass
class Country:
    code: str  # "uk": also the sponsor list it is checked against (sponsors.LISTS)
    name: str  # "the UK", for reasons
    places: list[str]  # normalized words: "united kingdom", "london"


@dataclass
class VisaRules:
    countries: list[Country] = field(default_factory=list)
    # Languages you don't speak (the profile lists Arabic and English): a posting that asks for one is rejected.
    languages: list[str] = field(default_factory=list)
    refresh_days: int = 7
    registers: Registers | None = None  # set by cli._load from data/sponsors/

    @classmethod
    def from_dict(cls, data: dict | None) -> VisaRules | None:
        if not data or not data.get("countries"):
            return None
        countries = [Country(code, c.get("name", code.upper()),
                             [w for w in (normalize_words(p) for p in c.get("places", [])) if w])
                     for code, c in data["countries"].items() if not code.startswith("_")]
        return cls(countries=countries, languages=[lang.lower() for lang in data.get("languages", [])],
                   refresh_days=int(data.get("refresh_days", 7)))

    @property
    def label(self) -> str:
        names = [c.name for c in self.countries]
        return ", ".join(names[:-1]) + " or " + names[-1] if len(names) > 1 else "".join(names)

    def place_in(self, texts: list[str]) -> tuple[str, Country] | None:
        """The first location text that names a place in one of the countries.

        "Dublin, OH" and "London, Ontario" are not: a text that also names a US
        state, Canada or the US is skipped.
        """
        for text in texts:
            if _ELSEWHERE.search(text or ""):
                continue
            words = f" {normalize_words(text)} "
            for country in self.countries:
                if any(f" {p} " in words for p in country.places):
                    return text, country
        return None


# Only the codes of states that have a town named like one of the places (Dublin OH, Berlin NH,
# Rome GA, Reading PA, London ON, Amsterdam NY, Munich ND, ...). Never DE: "Berlin, DE" is Germany.
_ELSEWHERE = re.compile(
    r",\s*(?:AL|AR|CA|CO|CT|GA|KY|MA|MD|ME|MI|MN|MS|MT|ND|NH|NY|OH|PA|SC|TN|TX|VA|WI|ON)\b"
    r"|(?i:\b(?:united\s+states|usa|u\.s\.a?|canada|ohio|california|massachusetts|ontario|georgia|texas|"
    r"new\s+hampshire|connecticut|virginia|indiana|kentucky|australia|new\s+zealand|south\s+africa|india)\b)"
)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [" ".join(p.split()) for p in parts if p.strip()]


def _short(sentence: str, width: int = 220) -> str:
    return sentence if len(sentence) <= width else sentence[:width - 1] + "…"


def _clauses(sentence: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT.split(sentence) if c.strip()]


def _refuses(clause: str) -> bool:
    return bool(_NEGATION.search(clause) and (_SPONSOR_WORD.search(clause) or _VISA_HELP.search(clause)))


def _aside(sentence: str, m: re.Match) -> bool:
    """Inside brackets: an example, "hard requirements (e.g. [x] days in office, unable to provide visas, etc)"."""
    before, after = sentence[:m.start()], sentence[m.end():]
    return before.count("(") > before.count(")") or after.count(")") > after.count("(")


def _sentence_refuses(sentence: str) -> bool:
    if _FIELD_REFUSAL.search(sentence):
        return True
    m = _LIST_REFUSAL.search(sentence)
    return bool(m) and not _aside(sentence, m) and not _OFFERED_AFTER.match(sentence, m.end())


def _offers(sentence: str) -> bool:
    return any(_OFFER.search(c) for c in _clauses(sentence)) or bool(
        _RELOCATION_WITH_VISA.search(sentence) and not _NEGATION.search(sentence))


@dataclass
class Posting:
    """What a posting says about visas, each a sentence as written."""

    offers: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    permits: list[str] = field(default_factory=list)  # a right to work you must already have
    relocation: list[str] = field(default_factory=list)  # help moving, no visa named


def read_posting(text: str) -> Posting:
    found = Posting()
    for sentence in _sentences(text):
        clauses = _clauses(sentence)
        if any(_refuses(c) for c in clauses) or _sentence_refuses(sentence):
            found.refusals.append(sentence)
        elif _offers(_TRANSFER.sub(" ", sentence)):
            found.offers.append(sentence)
        elif _offers(sentence):  # it offers only a transfer: a visa you must already have
            found.permits.append(sentence)
        # "Legally authorized to work in the Netherlands, or eligible for sponsorship" asks for nothing.
        elif _NEEDS_PERMIT.search(sentence) and not _SPONSOR_WORD.search(sentence):
            found.permits.append(sentence)
        # "Benefits vary by country and may include ... relocation support": a list of perks, not an offer.
        elif not _MAYBE.search(sentence) and any(_RELOCATION.search(c) and not _NEGATION.search(c) for c in clauses):
            found.relocation.append(sentence)
    return found


def hn_visa(job: Job) -> tuple[str | None, bool]:
    """A Hacker News header field about visas ("VISA", "NO VISA"): (the field, whether it refuses)."""
    if job.source != "hackernews":
        return None, False
    header = (job.description or "").split("\n", 1)[0]
    for part in header.split("|")[1:]:  # the first field is the company, which may be Visa
        if _HN_VISA.search(part):
            return " ".join(part.split()), bool(_NEGATION.search(part))
    return None, False


def language_needed(job: Job, languages: list[str]) -> str | None:
    """The reason a posting needs a language you don't speak, quoted; None when it doesn't."""
    if not languages:
        return None
    text = job.description or ""
    names = "|".join(re.escape(lang) for lang in languages) + "|deutsch|nederlands|español|espanol|italiano|suomi"
    asks = re.compile(
        # "Fluent German", "fluency in Dutch", "You speak German at C1", "Native or bilingual-level French"
        rf"\b(?:fluent|fluency|fluently|native|proficient|proficiency|speak|speaks|speaking|bilingual)\b[^.\n]{{0,30}}?"
        rf"\b(?:{names})\b"
        # "German language skills", "German fluency is required", "German (C1)"
        rf"|\b(?:{names})\b\s*(?:language\s+)?(?:skills|speaker|speaking|proficiency|fluency|knowledge|level)\b"
        rf"|\b(?:{names})\b[^.\n]{{0,20}}?\b[bc][12]\b"
        # "Excellent German and English": both asked for
        rf"|\b(?:{names})\s+(?:and|&)\s+english\b|\benglish\s+(?:and|&)\s+(?:{names})\b"
        rf"|\b(?:{names})\b\s+(?:is\s+)?(?:required|mandatory|a\s+must|essential)\b"
        r"|\b(?:fließend|fliessend|verhandlungssicher\w*|sehr\s+gute)\s+deutsch\w*|\bdeutschkenntnisse\b",
        re.I,
    )
    for sentence in _sentences(text):
        m = asks.search(sentence)
        if m and not _SOFTENER.search(sentence):
            return f'Asks for a language your profile does not list: "{_short(sentence)}"'
    words = re.findall(r"[a-zäöüßéèàáíóúñ]+", text.lower())
    if len(words) >= 40:
        for language, common in _FUNCTION_WORDS.items():
            if language in languages and sum(w in common for w in words) / len(words) >= _WRITTEN_IN_SHARE:
                return f'Written in {language.title()}: "{_short(_sentences(text)[0], 120)}"'
    return None


_RELOCATE_TO = re.compile(r"\b(?i:relocat\w*\s+to\s+(?:the\s+)?)([A-Z][\w-]+(?:\s+[A-Z][\w-]+)?)")


def _moves_elsewhere(text: str, country: Country) -> bool:
    """'Relocation to Cyprus' for a job filed under the Netherlands."""
    m = _RELOCATE_TO.search(text or "")
    return bool(m) and not any(f" {p} " in f" {normalize_words(m.group(1))} " for p in country.places)


def assess_visa(job: Job, place: str, country: Country, rules: VisaRules) -> Assessment:
    if job.remote_status == REMOTE:
        where = f'Remote, for people living in "{place}"'
    else:
        mode = {ONSITE: "On-site", HYBRID: "Hybrid"}.get(job.remote_status, "Based")
        where = f'{mode} in "{place}"'

    language = language_needed(job, rules.languages)
    if language:
        return Assessment(NOT_ELIGIBLE, [language], "language_required")

    posting = read_posting(job.description)
    field_text, hn_refuses = hn_visa(job)
    if field_text and hn_refuses:
        posting.refusals.insert(0, field_text)
    elif field_text:
        posting.offers.insert(0, f"{field_text} (Hacker News header)")

    listed = None
    # A remote role for people living there rarely comes with a visa: the posting must offer one.
    if rules.registers and country.code in LISTS and job.remote_status != REMOTE:
        listed = rules.registers.find(country.code, job.company, [place, job.location_raw or "", *job.allowed_locations])
    on_list = f'On {LISTS[country.code]}: "{listed.quote()}"' if listed else None

    if posting.offers:
        reasons = [f'{where}, {country.name}; the posting offers a visa: "{_short(posting.offers[0])}"']
        reasons += [f'But it also says, ask about it: "{_short(s)}"' for s in (posting.refusals + posting.permits)[:2]]
        return Assessment(VISA_SPONSOR, reasons + ([on_list] if on_list else []), "visa_offered")
    if posting.refusals:
        return Assessment(NOT_ELIGIBLE, [f'Does not sponsor visas: "{_short(posting.refusals[0])}"'], "no_sponsor")
    if posting.permits:
        return Assessment(NOT_ELIGIBLE, [f'Wants a right to work you would need a visa for: '
                                         f'"{_short(posting.permits[0])}"'], "no_sponsor")
    # "Senior Backend Engineer - Relocation to Cyprus", listed under the Netherlands: a move elsewhere.
    posting.relocation = [s for s in posting.relocation if not _moves_elsewhere(s, country)]
    if posting.relocation and _moves_elsewhere(job.title, country):
        posting.relocation = []
    if posting.relocation:
        reasons = [f'{where}, {country.name}; the posting offers help moving, not a visa by name (ask): '
                   f'"{_short(posting.relocation[0])}"']
        return Assessment(VISA_SPONSOR, reasons + ([on_list] if on_list else []), "relocation_offered")
    if listed:
        return Assessment(VISA_SPONSOR, [f'{where}, {country.name}; the company is on {LISTS[country.code]}: '
                                         f'"{listed.quote()}". '
                                         + ("The posting does not mention visas: ask" if job.description
                                            else "This source gives no posting text: read it and ask")],
                          "visa_register")
    if job.remote_status == REMOTE:
        missing = "and a remote role for people living there rarely comes with one"
    elif country.code in LISTS:
        missing = f"and {job.company or 'the company'} is not on {LISTS[country.code]}"
        if not rules.registers or country.code not in rules.registers.index:
            missing = f"and {LISTS[country.code]} is not downloaded (jobhunter sponsors --update)"
    else:
        missing = f"and {country.name} keeps no sponsor list"
    return Assessment(NOT_ELIGIBLE, [f"{where}, {country.name}: the posting does not offer a visa, {missing}"],
                      "no_visa_evidence")
