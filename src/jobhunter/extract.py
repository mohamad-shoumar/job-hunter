"""Deterministic field extraction from posting text.

Adapters fill whatever their source states directly. enrich() fills the rest
from the title and description, and never overwrites a value the source gave.
"""

from __future__ import annotations

import re

from .identity import canonical_url
from .models import CONTRACT, FULL_TIME, HYBRID, INTERNSHIP, ONSITE, PART_TIME, REMOTE, TEMPORARY, UNKNOWN, Job

# --- remote status ----------------------------------------------------------

_REMOTE_WORDS = re.compile(r"\b(?:remote|anywhere|work from home|wfh|distributed|telecommute)\b", re.I)
_HYBRID_WORDS = re.compile(r"\bhybrid\b", re.I)
_REMOTE_PROSE = re.compile(
    r"\b(?:fully|100%|completely|entirely|a) remote (?:role|position|job|team|company|opportunity)\b"
    r"|\bremote[- ](?:first|only)\b|\bwork (?:from|remotely from) anywhere\b"
    r"|\bthis (?:role|position|job) is (?:fully |100% )?remote\b",
    re.I,
)


def remote_status_from_location(location: str | None, title: str = "") -> str:
    """For sources whose only hint is a location string (Greenhouse, HN)."""
    text = f"{location or ''} {title or ''}"
    if _REMOTE_WORDS.search(text):
        return REMOTE
    if _HYBRID_WORDS.search(text):
        return HYBRID
    return ONSITE if (location or "").strip() else UNKNOWN


def normalize_workplace(value: str | None) -> str:
    v = re.sub(r"[^a-z]", "", (value or "").lower())
    if v in ("remote", "telecommute", "fullyremote"):
        return REMOTE
    if v == "hybrid":
        return HYBRID
    if v in ("onsite", "office", "inoffice", "inperson"):
        return ONSITE
    return UNKNOWN


# --- employment type --------------------------------------------------------


def normalize_employment_type(value: str | None) -> str | None:
    v = (value or "").lower()
    if not v:
        return None
    if "intern" in v:
        return INTERNSHIP
    if "part" in v:
        return PART_TIME
    if any(w in v for w in ("contract", "freelance", "contractor", "b2b")):
        return CONTRACT
    if "temp" in v:
        return TEMPORARY
    if "full" in v or "permanent" in v:
        return FULL_TIME
    return None


def employment_type_from_text(text: str) -> str | None:
    if re.search(r"\bfull[- ]time\b", text, re.I):
        return FULL_TIME
    if re.search(r"\b(?:contract (?:role|position|basis)|independent contractor|freelance (?:role|position|basis))\b", text, re.I):
        return CONTRACT
    if re.search(r"\bpart[- ]time\b", text, re.I):
        return PART_TIME
    return None


# --- years of experience ----------------------------------------------------

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
}
_COUNT = r"(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")"
# Field words that make "6+ years in software engineering" a requirement
# without the word "experience".
_FIELD = r"(?:software|engineering|development|developer|engineer|programming|backend|coding|professional|industry)"
_YOE = re.compile(
    rf"(?<![\d.$€£\w]){_COUNT}\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*{_COUNT}\s*\+?\s*)?(?:\(\d{{1,2}}\+?\)\s*)?"
    r"(?:years?|yrs?)(?:'|’)?\s+"
    r"(?:(?:of\s+)?(?:[\w/+#.-]+\s+){0,4}?(?:experience|exp)\b"
    rf"|(?:in|as|of)\s+(?:an?\s+|the\s+)?(?:[\w/+#.-]+\s+){{0,2}}?{_FIELD}\b)",
    re.I,
)
_OPTIONAL_CONTEXT = re.compile(r"\b(?:preferred|nice to have|nice-to-have|bonus|ideally|a plus|is a plus)\b", re.I)
_BRAG_CONTEXT = re.compile(r"\b(?:we have|our|company has|with over|for over)\s*$", re.I)


def extract_required_yoe(text: str) -> int | None:
    """The strictest 'N+ years of experience' stated as a requirement.

    Counts may be words ('seven years of experience') and the field may stand
    in for 'experience' ('6+ years in software engineering'). Lines marked
    preferred/nice-to-have are ignored, as are company boasts ('our 15 years
    of experience').
    """
    best = None
    for line in (text or "").split("\n"):
        if _OPTIONAL_CONTEXT.search(line):
            continue
        for m in _YOE.finditer(line):
            if _BRAG_CONTEXT.search(line[max(0, m.start() - 20):m.start()]):
                continue
            count = m.group(1).lower()
            years = int(count) if count.isdigit() else _NUMBER_WORDS[count]
            if 1 <= years <= 15:
                best = years if best is None else max(best, years)
    return best


# --- skills -----------------------------------------------------------------

SKILL_PATTERNS = {
    "python": r"\bpython\b",
    "fastapi": r"\bfast\s?api\b",
    "django": r"\bdjango\b",
    "flask": r"\bflask\b",
    "sqlalchemy": r"\bsqlalchemy\b",
    "celery": r"\bcelery\b",
    "pandas": r"\bpandas\b",
    "numpy": r"\bnumpy\b",
    "pydantic": r"\bpydantic\b",
    "asyncio": r"\basyncio\b",
    "postgresql": r"\bpostgres(?:ql)?\b",
    "mysql": r"\bmysql\b",
    "sql": r"\bsql\b",
    "mongodb": r"\bmongo(?:db)?\b",
    "redis": r"\bredis\b",
    "elasticsearch": r"\belastic\s?search\b",
    "kafka": r"\bkafka\b",
    "rabbitmq": r"\brabbitmq\b",
    "aws": r"\baws\b|\bamazon web services\b",
    "gcp": r"\bgcp\b|\bgoogle cloud\b",
    "azure": r"\bazure\b",
    "serverless": r"\bserverless\b|\baws lambda\b|\blambda functions?\b",
    "firebase": r"\bfirebase\b",
    "datadog": r"\bdatadog\b",
    "grafana": r"\bgrafana\b",
    "docker": r"\bdocker\b",
    "kubernetes": r"\bkubernetes\b|\bk8s\b",
    "terraform": r"\bterraform\b",
    "ci/cd": r"\bci\s?/\s?cd\b",
    "rest api": r"\brest(?:ful)?\s?(?:api|apis|services)\b",
    "graphql": r"\bgraphql\b",
    "grpc": r"\bgrpc\b",
    "microservices": r"\bmicro-?services\b",
    "distributed systems": r"\bdistributed systems?\b",
    "react": r"\breact(?:\.?js)?\b(?!\s+native)",
    "typescript": r"\btypescript\b",
    "javascript": r"\bjavascript\b",
    "nodejs": r"\bnode\.?js\b",
    "nextjs": r"\bnext\.?js\b",
    "llm": r"\bllms?\b|\blarge language models?\b",
    "rag": r"\brag\b|\bretrieval[- ]augmented\b",
    "langchain": r"\blangchain\b",
    "langgraph": r"\blanggraph\b",
    "ai agents": r"\bai agents?\b|\bagentic\b",
    "machine learning": r"\bmachine learning\b",
    "pytorch": r"\bpytorch\b",
    "trading": r"\b(?:algorithmic|algo|quantitative|systematic|high[- ]frequency|electronic)?\s?trading\b",
    "backtesting": r"\bback-?test(?:ing|s)?\b",
    "crypto": r"\bcrypto(?:currency|currencies)?\b|\bblockchain\b|\bdefi\b|\bweb3\b",
    "golang": r"\bgolang\b",
    "java": r"\bjava\b(?!\s*script)",
    "rust": r"\brust\b",
    "linux": r"\blinux\b",
}
_SKILL_RES = {name: re.compile(pattern, re.I) for name, pattern in SKILL_PATTERNS.items()}


def extract_skills(text: str) -> list[str]:
    return [name for name, pattern in _SKILL_RES.items() if pattern.search(text or "")]


# --- salary -----------------------------------------------------------------

_CURRENCY = r"[$€£]|USD|EUR|GBP|CAD|AUD|CHF|AED|SGD|SAR"
_AMOUNT = r"\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?\s*[kK]?"
_SALARY = re.compile(
    rf"(?P<cur>{_CURRENCY})\s?(?P<a>{_AMOUNT})\s*(?:-|–|—|to)\s*(?:{_CURRENCY})?\s?(?P<b>{_AMOUNT})"
    r"(?P<tail>(?:\s*[A-Z]{3}\b)?(?:\s*(?i:/|per|an?)\s*(?i:year|yr|annum|hour|hr|month|mo)\b"
    r"|\s*(?i:annually|yearly|hourly|monthly)\b)?)",
)
_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


def _amount(raw: str) -> float:
    raw = raw.strip()
    multiplier = 1000 if raw[-1:] in "kK" else 1
    digits = re.sub(r"[kK\s]", "", raw)
    if re.search(r"[,.]\d{3}$", digits):
        digits = re.sub(r"[,.]", "", digits)
    return float(digits.replace(",", "")) * multiplier


def extract_salary(text: str) -> dict | None:
    m = _SALARY.search(text or "")
    if not m:
        return None
    try:
        low, high = _amount(m.group("a")), _amount(m.group("b"))
    except ValueError:
        return None
    if m.group("b").strip()[-1:] in "kK" and low < 1000:  # "$90-120k"
        low *= 1000
    tail = m.group("tail").lower()
    if re.search(r"hour|hr", tail):
        period = "hour"
    elif re.search(r"month|\bmo\b", tail):
        period = "month"
    elif high >= 10000:
        period = "year"
    else:
        return None  # "$50 - 60" with no unit: too ambiguous to store as numbers
    return {
        "salary_min": low,
        "salary_max": high,
        "salary_currency": _SYMBOLS.get(m.group("cur"), m.group("cur")),
        "salary_period": period,
        "salary_raw": m.group(0).strip(),
    }


# --- contractor / employer of record ----------------------------------------

_EOR_TERMS = re.compile(
    r"\b(?:employer of record|deel|remote\.com|oyster ?hr|omnipresent|papaya global|velocity global|"
    r"globalization partners|remofirst|skuad|workmotion|atlas hxm|safeguard global)\b",
    re.I,
)
_EOR_ACRONYM = re.compile(r"\bEOR\b")
_CONTRACTOR_TERMS = re.compile(
    r"\b(?:independent contractor|contractor (?:basis|agreement|role|position)|as a contractor|"
    r"b2b (?:contract|agreement)|freelance(?:r)? (?:basis|contract))\b",
    re.I,
)


def extract_eor_mentions(text: str) -> list[str]:
    found = {m.group(0).lower() for m in _EOR_TERMS.finditer(text or "")}
    if _EOR_ACRONYM.search(text or ""):
        found.add("eor")
    return sorted(found)


def extract_contractor_mentions(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _CONTRACTOR_TERMS.finditer(text or "")})


# --- enrichment -------------------------------------------------------------


def _merge(existing: list[str], extra: list[str]) -> list[str]:
    seen = dict.fromkeys(existing)
    seen.update(dict.fromkeys(extra))
    return list(seen)


def enrich(job: Job) -> Job:
    text = f"{job.title}\n{job.description}"
    if job.remote_status == UNKNOWN and _REMOTE_PROSE.search(text):
        job.remote_status = REMOTE
    job.employment_type = normalize_employment_type(job.employment_type) or employment_type_from_text(job.description)
    if job.required_yoe is None:
        job.required_yoe = extract_required_yoe(job.description)
    job.skills = _merge([s.lower() for s in job.skills], extract_skills(f"{text}\n{' '.join(job.tags)}"))
    if job.salary_min is None and job.salary_max is None:
        found = extract_salary(job.salary_raw or "") or extract_salary(text)
        if found:
            for key, value in found.items():
                if key != "salary_raw" or not job.salary_raw:
                    setattr(job, key, value)
    job.contract_info = _merge(job.contract_info, extract_eor_mentions(job.description) + extract_contractor_mentions(job.description))
    job.application_url = canonical_url(job.application_url)
    job.source_url = canonical_url(job.source_url) or job.source_url
    job.company = " ".join((job.company or "").split()) or "Unknown company"
    job.title = " ".join((job.title or "").split()) or "Unknown role"
    return job
