"""In-memory symptom index and deterministic matcher, built once at server startup from the
committed data/index/symptoms.json artifact (step 25b).

No file I/O and no network in the request path (CLAUDE.md rules 3/4), and no model call: matching
is stemmed-keyword overlap, weighted by how rare each word is across the manuals, with a minimum
score, a minimum number of matched words and a not-found path. A customer's words are only ever
used to *find* a stored row; nothing the customer said is ever written into a result.

How a query is scored against one symptom (a symptom is a table row's Problem phrases together
with the rows that continue it):

  1. The query and the manual text are lower-cased, split into words, stripped of stopwords and
     light-stemmed ("leaking"/"leaks" -> "leak"); a small curated synonym table folds a few
     everyday words onto the manual's own ("noise" -> "sound", "start" -> "operate").
     Appliance-type words ("washer", "fridge") are not matched on; they only narrow the search.
  2. Each query word has a weight, its inverse document frequency over all symptoms (rare words
     weigh more); a word that appears nowhere in the manuals counts for half of the heaviest.
  3. score = (weight of query words found in the symptom's own phrases
              + CAUSE_WEIGHT x weight of the others found in its cause text) / weight of all query words.
  4. A symptom matches only if at least one query word is in its own phrases (a cause alone never
     matches), it has at least MIN_MATCHED_TERMS matched words (or the query has only one content
     word), and score >= MIN_SCORE.

The thresholds are tuned on the paraphrase and off-topic cases in tests/unit/test_retrieval_symptoms.py
and evals/cases.yaml, not derived from theory.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from fixit_mcp.domain.appliance_types import normalize_appliance_type
from fixit_mcp.domain.models import SymptomRecord

DEFAULT_SYMPTOMS_PATH = Path(__file__).resolve().parents[3] / "data" / "index" / "symptoms.json"

MIN_SCORE = 0.5
MIN_MATCHED_TERMS = 2
CAUSE_WEIGHT = 0.4
OOV_WEIGHT_SHARE = 0.5  # of the heaviest known word's weight
MAX_MATCHES = 3
MAX_NEAREST = 3

_STOPWORDS = frozenset(
    """a an the is are was were be been being am do does did doing done will would can could should
    shall may might must have has had having i me my mine we our us you your it its it's this that
    these those there here to of in on at for with from by as and or but so if then than too very
    just also really quite not no nor please help thing things something anything someone again now
    still always sometimes when while why how what which who whom whose get gets got going go goes
    keeps keep kept seem seems seemed look looks looked like about up down out off over into onto
    many much more most lot lots bit some any all every each other another one two
    make makes making made come comes came coming show shows showing say says saying happen happens""".split()
)

# Everyday word -> the manual's word (both in stemmed form, e.g. 'operat'). Each entry exists because a test
# paraphrase needs it; add one only with a test.
_SYNONYMS = {
    "nois": "sound",
    "noisy": "sound",
    "loud": "sound",
    "drip": "leak",
    "puddl": "leak",
    "seep": "leak",
    "start": "operat",
    "work": "operat",
    "function": "operat",
    "smell": "odor",
    "odour": "odor",
    "stink": "odor",
    "foam": "sud",
    "foamy": "sud",
    "frozen": "freez",
}

_CONTRACTIONS = (
    (re.compile(r"\bwon['’]?t\b"), "will not"),
    (re.compile(r"\bcan['’]?t\b"), "can not"),
    (re.compile(r"n['’]t\b"), " not"),
    (re.compile(r"['’]s\b"), ""),
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def stem(word: str) -> str:
    """A deliberately light suffix stripper: enough to match 'leaking', 'leaks' and 'leak'."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("es") and word[:-2].endswith(("ch", "sh", "x", "z", "s")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def _words(text: str) -> list[str]:
    lowered = text.lower()
    for pattern, replacement in _CONTRACTIONS:
        lowered = pattern.sub(replacement, lowered)
    return _WORD_RE.findall(lowered)


def _content_words(text: str) -> list[str]:
    return [w for w in _words(text) if w not in _STOPWORDS]


def _fold(word: str) -> str:
    stemmed = stem(word)
    return _SYNONYMS.get(stemmed, stemmed)


def tokenize(text: str) -> list[str]:
    """Content words of `text`: lower-cased, contractions opened, stopwords dropped, stemmed, folded."""
    return [_fold(w) for w in _content_words(text)]


# --- appliance-type words in a query ----------------------------------------------------

# Words that name an appliance type in a customer's description. "range" is left out on purpose: it is
# an ordinary English word ("outside the normal range") and must not narrow a search by itself.
_TYPE_PHRASES: dict[str, str] = {
    "washer": "washing_machine",
    "washing machine": "washing_machine",
    "clothes washer": "washing_machine",
    "dryer": "dryer",
    "clothes dryer": "dryer",
    "fridge": "refrigerator",
    "refrigerator": "refrigerator",
    "freezer": "refrigerator",
    "dishwasher": "dishwasher",
    "dish washer": "dishwasher",
    "oven": "range",
    "stove": "range",
}
_MULTIWORD_TYPE_PHRASES = tuple(sorted((p for p in _TYPE_PHRASES if " " in p), key=len, reverse=True))
_TYPE_WORDS = frozenset(p for p in _TYPE_PHRASES if " " not in p)


def appliance_types_in(text: str) -> set[str]:
    """The canonical appliance types the customer's own words name ("my fridge ..." -> refrigerator)."""
    lowered = " " + " ".join(_words(text)) + " "
    return {canonical for phrase, canonical in _TYPE_PHRASES.items() if f" {phrase} " in lowered}


def query_terms(text: str) -> list[str]:
    """The distinct content words to match on, in order; appliance-type words are context, not terms."""
    lowered = " " + " ".join(_words(text)) + " "
    for phrase in _MULTIWORD_TYPE_PHRASES:
        lowered = lowered.replace(f" {phrase} ", " ")
    return list(dict.fromkeys(_fold(w) for w in _content_words(lowered) if w not in _TYPE_WORDS))


# --- index ---------------------------------------------------------------------------------


@dataclass
class SymptomGroup:
    """One symptom as the manual words it, with every row that belongs to it (its causes/actions)."""

    manual_id: str
    brand: str
    model: str
    appliance_type: str  # canonical
    phrases: list[str]
    symptom_label: str
    rows: list[SymptomRecord]
    symptom_terms: frozenset[str] = field(default_factory=frozenset)
    cause_terms: frozenset[str] = field(default_factory=frozenset)

    @property
    def page(self) -> int:
        return self.rows[0].source_page

    @property
    def section(self) -> str | None:
        return self.rows[0].source_section


@dataclass(frozen=True)
class ScoredGroup:
    group: SymptomGroup
    score: float
    matched: int  # distinct query words found (own phrases or causes)
    matched_in_symptom: int


@dataclass
class SymptomIndex:
    groups: list[SymptomGroup]
    idf: dict[str, float] = field(default_factory=dict)

    @property
    def manual_ids(self) -> set[str]:
        return {g.manual_id for g in self.groups}

    def _weight(self, term: str) -> float:
        known = self.idf.get(term)
        if known is not None:
            return known
        return OOV_WEIGHT_SHARE * max(self.idf.values(), default=1.0)

    def _candidates(self, manual_ids: set[str] | None, appliance_type: str | None) -> list[SymptomGroup]:
        return [
            g
            for g in self.groups
            if (manual_ids is None or g.manual_id in manual_ids)
            and (appliance_type is None or g.appliance_type == appliance_type)
        ]

    def score_all(
        self, terms: list[str], manual_ids: set[str] | None = None, appliance_type: str | None = None
    ) -> list[ScoredGroup]:
        """Every candidate group with at least one query word in its own phrases, best first."""
        if not terms:
            return []
        total = sum(self._weight(t) for t in terms)
        scored: list[ScoredGroup] = []
        for g in self._candidates(manual_ids, appliance_type):
            in_symptom = [t for t in terms if t in g.symptom_terms]
            if not in_symptom:
                continue
            in_cause = [t for t in terms if t not in g.symptom_terms and t in g.cause_terms]
            weight = sum(self._weight(t) for t in in_symptom) + CAUSE_WEIGHT * sum(
                self._weight(t) for t in in_cause
            )
            scored.append(
                ScoredGroup(
                    group=g,
                    score=weight / total,
                    matched=len(in_symptom) + len(in_cause),
                    matched_in_symptom=len(in_symptom),
                )
            )
        order = {id(g): i for i, g in enumerate(self.groups)}
        # Ties on score go to the symptom whose own phrases are most fully covered by the query.
        scored.sort(
            key=lambda s: (
                -round(s.score, 6),
                -s.matched_in_symptom / max(len(s.group.symptom_terms), 1),
                order[id(s.group)],
            )
        )
        return scored

    def search(
        self, terms: list[str], manual_ids: set[str] | None = None, appliance_type: str | None = None
    ) -> list[ScoredGroup]:
        """The groups that clear the matching rules (see the module docstring), best first."""
        needed = min(MIN_MATCHED_TERMS, len(terms))
        return [
            s
            for s in self.score_all(terms, manual_ids, appliance_type)
            if s.score >= MIN_SCORE and s.matched >= needed
        ]

    def nearest_phrases(
        self,
        terms: list[str],
        manual_ids: set[str] | None = None,
        appliance_type: str | None = None,
        limit: int = MAX_NEAREST,
    ) -> list[str]:
        """The manual's own first phrase of the closest symptoms that share at least one word with the
        query but did not clear the matching rules -- a verbatim "did you mean", never a cause."""
        phrases: list[str] = []
        for s in self.score_all(terms, manual_ids, appliance_type):
            phrase = s.group.phrases[0]
            if phrase not in phrases:
                phrases.append(phrase)
            if len(phrases) == limit:
                break
        return phrases


def build_groups(records: list[SymptomRecord]) -> list[SymptomGroup]:
    """Rows that continue a symptom join the group of the row above (same manual, in file order)."""
    groups: list[SymptomGroup] = []
    for record in records:
        if record.symptom_continued and groups and groups[-1].manual_id == record.manual_id:
            groups[-1].rows.append(record)
            continue
        groups.append(
            SymptomGroup(
                manual_id=record.manual_id,
                brand=record.brand,
                model=record.model,
                appliance_type=normalize_appliance_type(record.appliance_type),
                phrases=list(record.symptom),
                symptom_label=record.symptom_label,
                rows=[record],
            )
        )
    for g in groups:
        label_terms = [] if g.symptom_label.lower() == "problem" else tokenize(g.symptom_label)
        g.symptom_terms = frozenset(tokenize(" ".join(g.phrases)) + label_terms)
        causes = " ".join(c for r in g.rows for c in r.possible_causes)
        g.cause_terms = frozenset(tokenize(causes)) - g.symptom_terms
    return groups


def build_index(records: list[SymptomRecord]) -> SymptomIndex:
    groups = build_groups(records)
    document_frequency: dict[str, int] = {}
    for g in groups:
        for term in g.symptom_terms | g.cause_terms:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    n = max(len(groups), 1)
    return SymptomIndex(
        groups=groups, idf={term: math.log(1 + n / df) for term, df in document_frequency.items()}
    )


def load_symptom_index(path: Path | None = None) -> SymptomIndex:
    """Load data/index/symptoms.json. Call once at server startup, never per request."""
    path = path or DEFAULT_SYMPTOMS_PATH
    raw = json.loads(path.read_text())
    return build_index([SymptomRecord.model_validate(item) for item in raw])
