"""In-memory symptom index and deterministic matcher, built once at server startup from the
committed data/index/symptoms.json artifact (step 25b, matching improved in step 27c).

No file I/O and no network in the request path (CLAUDE.md rules 3/4), and no model call: matching
is keyword overlap, weighted by how rare each word is across the manuals, with a not-found path. A
customer's words are only ever used to *find* a stored row; nothing the customer said is ever written
into a result. Every step below can only rename a word or block a match, never invent one, and the
matcher prefers not_found to a wrong cited answer.

How a customer's description becomes terms (`analyze_query`):

  1. Lower-cased, contractions opened ("won't" -> "will not"), articles dropped. A single-character
     slip on a word of five or more letters ("dispencer", "wrinkeld") is mended, but only when exactly
     one known word is one edit away (`Spelling`); otherwise the word is left alone.
  2. Appliance-type words ("washer", "fridge") are set aside: they narrow the search, never match.
  3. Reviewed multi-word phrases become the manual's words ("won't turn on" -> not + operate, "water
     all over" -> leak); `_PHRASES`. A "does not happen" phrase or any `not`/`no`/`never` marks the
     description as negated.
  4. Fillers ("really", "way") and garments ("shirts") are ignored. Every other word is stemmed and
     folded through the reviewed synonym table (`_SYNONYM_WORDS`: "shake" -> "rock", "damp" -> "wet").
     Every synonym and phrase target is a word the stored rows use (a test checks it).

How a description is scored against one symptom (a symptom is a table row's Problem phrases together
with the rows that continue it):

  a. Each query word has a weight, its inverse document frequency over all symptoms (rare words
     weigh more); a word that appears nowhere in the manuals counts for OOV_WEIGHT_SHARE of the
     heaviest: an unknown word is a reason to doubt a match, not something to ignore.
  b. score = (weight of query words found in the symptom's own phrases
              + CAUSE_WEIGHT x weight of the others found in its cause text) / weight of all query words.
  c. A symptom matches only if score >= MIN_SCORE and either at least MIN_MATCHED_TERMS query words
     (or all of them, for a one-word query) are in its own phrases, or one is DISTINCTIVE (used by at
     most DISTINCTIVE_MAX_SYMPTOMS symptoms, like "suds"). A cause alone never matches.
  d. Polarity must agree: "won't spin" is not matched to "pauses during spin" (a symptom is negated
     when its own wording is: "won't drain", "not cooling").
  e. One common word that fits more than MAX_MATCHES symptoms ("noisy" -> sound) matches none of them.

The thresholds and tables are tuned on the paraphrase bank (tests/fixtures/symptom_paraphrases.yaml,
tests/unit/test_symptom_bank.py), which fails on any wrong cited answer, and on the cases in
tests/unit/test_retrieval_symptoms.py. Matching is still keyword-based and can miss things; it says
not_found rather than guess.
"""

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
CAUSE_WEIGHT = 0.25
OOV_WEIGHT_SHARE = 0.6  # of the heaviest known word: one unknown word still passes (0.62), two do not (0.45)
MAX_MATCHES = 3
MAX_NEAREST = 3
# A symptom word that appears in at most this many symptoms is specific enough to carry a match alone.
DISTINCTIVE_MAX_SYMPTOMS = 2
MIN_SPELLING_LENGTH = 5  # shorter words are never "corrected": one slip would reach too many real words

_NEGATIONS = frozenset("not no never without nor neither".split())

_STOPWORDS = frozenset(
    """a an the is are was were be been being am do does did doing done will would can could should
    shall may might must have has had having i me my mine we our us you your it its it's this that
    these those there here to of in on at for with from by as and or but so if then than too very
    just also quite please help thing things something anything someone again now
    still sometimes when while why how what which who whom whose get gets got going go goes
    keeps keep kept seem seems seemed look looks looked like about up down out off over into onto
    many much more most lot lots bit some any all every each other another one two
    make makes making made come comes came coming show shows showing say says saying happen happens
    put puts putting turn turns turning after before""".split()
)

# Intensifiers and filler: they add nothing to what is wrong, and must not count against a customer
# ("way too many suds", "shaking like crazy"). A word that is neither here nor in the manuals is NOT
# ignored: an unknown word is a reason to doubt a match ("my car won't start").
_FILLERS = frozenset(
    """way really super totally completely extremely absolutely literally actually basically honestly
    constantly always anymore lately today suddenly randomly crazy violently badly terribly seriously
    pretty rather kinda sorta floor little tiny""".split()
)

# Words for things a customer wears or washes; the symptom is about the machine, so they are context.
_GARMENTS = frozenset(
    """shirt shirts sweater sweaters sock socks towel towels jean jeans pants blouse blouses dress
    dresses sheets""".split()
)

_DETERMINERS = frozenset("the a an my our your its his her their this that".split())

# Everyday word -> the manual's own word. Reviewed one by one; every target is a word the stored rows
# use in a symptom (tests/unit/test_retrieval_symptoms.py checks it against data/index/symptoms.json).
# Keys are plain words; they are stemmed when the table is built.
_SYNONYM_WORDS = {
    # sound
    "noise": "sound",
    "noisy": "sound",
    "loud": "sound",
    "squeal": "squeak",
    "screech": "squeak",
    "creak": "squeak",
    "buzz": "hum",
    "glug": "gurgle",
    # moving / shaking
    "shake": "rock",
    "shaky": "rock",
    "vibrate": "rock",
    "vibration": "rock",
    "wobble": "rock",
    "wobbly": "rock",
    "bounce": "rock",
    "walk": "move",
    "jump": "move",
    # water
    "drip": "leak",
    "puddle": "leak",
    "seep": "leak",
    "soak": "wet",
    "soaked": "wet",
    "soggy": "wet",
    "damp": "wet",
    "sodden": "wet",
    "drenched": "wet",
    "foam": "suds",
    "foamy": "suds",
    # works / does not work
    "start": "operate",
    "work": "operate",
    "function": "operate",
    # smell
    "smell": "odor",
    "odour": "odor",
    "stink": "odor",
    # taste
    "funny": "poor",
    "bad": "poor",
    "weird": "poor",
    "strange": "poor",
    "odd": "poor",
    "nasty": "poor",
    # appearance of clothes
    "grey": "gray",
    "dingy": "gray",
    "crease": "wrinkle",
    "creased": "wrinkle",
    "torn": "tear",
    "fluff": "lint",
    "linty": "lint",
    # other
    "alarm": "beep",
    "frozen": "freeze",
    # "the light is on" is how a customer says what the manual calls "is lit"
    "light": "lit",
}

# Multi-word phrases -> canonical tokens (stems); "!neg" means the phrase says something does NOT
# happen. Matched on stems, with articles and possessives ignored, longest phrase first. Reviewed one
# by one, like the synonyms; every canonical token is a word the stored rows use.
_PHRASES: list[tuple[str, str]] = [
    # does not work
    ("turn on", "operate"),
    ("power on", "operate"),
    ("power up", "operate"),
    ("switch on", "operate"),
    ("start up", "operate"),
    ("nothing happens", "!neg operate"),
    ("no power", "!neg operate"),
    ("not respond", "!neg operate"),
    ("stopped working", "!neg operate"),
    ("stop working", "!neg operate"),
    ("quit working", "!neg operate"),
    ("dead", "!neg operate"),
    ("died", "!neg operate"),
    # does not drain
    ("standing water", "!neg drain"),
    ("water sits", "!neg drain"),
    ("water stays", "!neg drain"),
    ("will not go down", "!neg drain"),
    ("never drains", "!neg drain"),
    # leaks
    ("water on floor", "leak"),
    ("water all over", "leak"),
    ("water everywhere", "leak"),
    # too cold / not enough
    ("not enough", "low"),
    ("too little", "low"),
    ("not cold", "!neg cool"),
    ("too warm", "!neg cool"),
    ("warm inside", "!neg cool"),
    # difficult
    ("hard to", "difficult"),
    ("tough to", "difficult"),
    # lumps of fabric
    ("fuzz balls", "pill"),
    ("little balls", "pill"),
    ("fabric balls", "pill"),
    # harmless intensifiers
    ("like crazy", ""),
    ("all the time", ""),
]

_CONTRACTIONS = (
    (re.compile(r"\bwon['’]?t\b"), "will not"),
    (re.compile(r"\bcan['’]?t\b"), "can not"),
    (re.compile(r"\bcannot\b"), "can not"),
    (re.compile(r"\b(do|does|did|is|are|was|were|has|have|had|could|would|should)n['’]?t\b"), r"\1 not"),
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


# Folding table in stemmed form. A synonym key is also folded when it appears in a stored row, so a
# row that says "alarm" in its causes carries "beep" -- the same fold on both sides.
_SYNONYMS = {stem(k): stem(v) for k, v in _SYNONYM_WORDS.items()}
_PHRASE_STEMS: list[tuple[tuple[str, ...], tuple[str, ...]]] = sorted(
    (
        (tuple(stem(w) for w in phrase.split()), tuple(stem(t) if t != "!neg" else t for t in out.split()))
        for phrase, out in _PHRASES
    ),
    key=lambda pair: -len(pair[0]),
)


def _words(text: str) -> list[str]:
    lowered = text.lower()
    for pattern, replacement in _CONTRACTIONS:
        lowered = pattern.sub(replacement, lowered)
    return _WORD_RE.findall(lowered)


def _content_words(text: str) -> list[str]:
    return [w for w in _words(text) if w not in _STOPWORDS and w not in _NEGATIONS]


def _fold(word: str) -> str:
    stemmed = stem(word)
    return _SYNONYMS.get(stemmed, stemmed)


def tokenize(text: str) -> list[str]:
    """Content words of `text`: lower-cased, contractions opened, stopwords dropped, stemmed, folded."""
    return [_fold(w) for w in _content_words(text)]


def is_negated(text: str) -> bool:
    """Does `text` say that something does not happen ("won't drain", "not cooling", "no fill")?"""
    return any(w in _NEGATIONS for w in _words(text))


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


# --- one query, analysed -------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryAnalysis:
    terms: list[str]  # distinct content words to match on, in order
    negated: bool  # the customer says something does NOT happen ("won't drain", "not cooling")
    types: frozenset[str]  # canonical appliance types the customer's own words name


def _forms(term: str) -> set[str]:
    """Plausible spellings a stem can come from ("wrinkl" -> wrinkle, wrinkled, wrinkling, ...)."""
    forms = {term, term + "e", term + "s", term + "es", term + "ed", term + "d", term + "ing", term + "er"}
    forms |= {term + "ers", term + "y", term + "ly"}
    if term and term[-1] not in "aeiou":
        forms |= {term + term[-1] + "ed", term + term[-1] + "ing"}
    return forms


_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _one_edit(word: str) -> set[str]:
    """Every string one slip away: a deleted, inserted or substituted letter, or two swapped."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = {left + right[1:] for left, right in splits if right}
    out |= {left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1}
    out |= {left + c + right[1:] for left, right in splits if right for c in _LETTERS}
    out |= {left + c + right for left, right in splits for c in _LETTERS}
    out.discard(word)
    return out


class Spelling:
    """Light, deterministic tolerance for a single-character slip on a longer word.

    A word is only "corrected" when it is at least MIN_SPELLING_LENGTH letters, is not itself a word
    this matcher knows, and exactly ONE known word (counted by what it folds to) is one edit away.
    Two candidates, or none, leave the word alone: the matcher would rather not understand a word
    than guess which one was meant.
    """

    def __init__(self, terms: frozenset[str]) -> None:
        self.terms = terms
        forms: dict[str, str] = {}
        for term in terms:
            for form in _forms(term):
                if _fold(form) == term:  # a real spelling of the term, not just a suffix added to it
                    forms.setdefault(form, term)
        for key, target in _SYNONYM_WORDS.items():
            for form in _forms(stem(key)) | {key}:
                if _fold(form) == _fold(target):
                    forms.setdefault(form, _fold(target))
        for phrase in _TYPE_PHRASES:
            for word in phrase.split():
                forms.setdefault(word, "type:" + word)
        for phrase_stems, _out in _PHRASE_STEMS:
            for word in phrase_stems:
                for form in _forms(word):
                    forms.setdefault(form, "phrase:" + word)
        self.forms = forms
        self.fixed = _STOPWORDS | _FILLERS | _GARMENTS | _DETERMINERS | _NEGATIONS | frozenset(_TYPE_PHRASES)

    def correct(self, word: str) -> str:
        if len(word) < MIN_SPELLING_LENGTH or not word.isalpha():
            return word
        if word in self.fixed or word in self.forms or _fold(word) in self.terms or stem(word) in _SYNONYMS:
            return word
        candidates = sorted(c for c in _one_edit(word) if c in self.forms)
        if candidates and len({self.forms[c] for c in candidates}) == 1:
            return candidates[0]
        return word


def analyze_query(text: str, spelling: Spelling | None = None) -> QueryAnalysis:
    """Turn a customer's description into what to match on.

    Contractions are opened, articles dropped, single-character slips mended (with `spelling`),
    appliance-type words set aside, reviewed multi-word phrases replaced by the manual's words ("won't
    turn on" -> not + operate), fillers and garments ignored, and every other word stemmed and folded
    through the reviewed synonym table. A word the manuals do not use is kept as a term: it is a reason
    to doubt a match, not something to ignore.
    """
    words = [w for w in _words(text) if w not in _DETERMINERS]
    if spelling is not None:
        words = [spelling.correct(w) for w in words]
    types: set[str] = set()
    tokens: list[str] = []
    i = 0
    while i < len(words):
        two = " ".join(words[i : i + 2])
        if two in _TYPE_PHRASES and " " in two:
            types.add(_TYPE_PHRASES[two])
            i += 2
            continue
        stems = tuple(stem(w) for w in words[i:])
        for phrase_stems, out in _PHRASE_STEMS:
            if stems[: len(phrase_stems)] == phrase_stems:
                tokens.extend(out)
                i += len(phrase_stems)
                break
        else:
            word = words[i]
            i += 1
            if word in _TYPE_WORDS:
                types.add(_TYPE_PHRASES[word])
            elif word in _NEGATIONS:
                tokens.append("!neg")
            elif word in _STOPWORDS or word in _FILLERS or word in _GARMENTS:
                continue
            else:
                tokens.append(_fold(word))
    terms = list(dict.fromkeys(t for t in tokens if t != "!neg"))
    return QueryAnalysis(terms=terms, negated="!neg" in tokens, types=frozenset(types))


def appliance_types_in(text: str) -> set[str]:
    """The canonical appliance types the customer's own words name ("my fridge ..." -> refrigerator)."""
    return set(analyze_query(text).types)


def query_terms(text: str) -> list[str]:
    """The distinct content words to match on, in order; appliance-type words are context, not terms."""
    return analyze_query(text).terms


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
    negated: bool = False  # the manual's own wording says something does NOT happen ("won't drain")

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
    distinctive: bool = False  # a matched symptom word appears in at most DISTINCTIVE_MAX_SYMPTOMS symptoms


@dataclass
class SymptomIndex:
    groups: list[SymptomGroup]
    idf: dict[str, float] = field(default_factory=dict)
    spelling: Spelling | None = None
    symptom_df: dict[str, int] = field(
        default_factory=dict
    )  # word -> how many symptoms use it in their own phrases

    def analyze(self, text: str) -> QueryAnalysis:
        """A customer's description analysed against this index (spelling mended against its words)."""
        return analyze_query(text, self.spelling)

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
        self,
        terms: list[str],
        manual_ids: set[str] | None = None,
        appliance_type: str | None = None,
        negated: bool | None = None,
    ) -> list[ScoredGroup]:
        """Every candidate group with at least one query word in its own phrases, best first. When
        `negated` is given, only groups whose own wording has the same polarity are considered: a
        customer whose washer "won't spin" is not sent to the row about how it "pauses during spin"."""
        if not terms:
            return []
        total = sum(self._weight(t) for t in terms)
        scored: list[ScoredGroup] = []
        for g in self._candidates(manual_ids, appliance_type):
            if negated is not None and g.negated != negated:
                continue
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
                    distinctive=any(
                        self.symptom_df.get(t, 0) <= DISTINCTIVE_MAX_SYMPTOMS for t in in_symptom
                    ),
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
        self,
        terms: list[str],
        manual_ids: set[str] | None = None,
        appliance_type: str | None = None,
        negated: bool | None = None,
    ) -> list[ScoredGroup]:
        """The groups that clear the matching rules (see the module docstring), best first."""
        needed = min(MIN_MATCHED_TERMS, len(terms))
        found = [
            s
            for s in self.score_all(terms, manual_ids, appliance_type, negated)
            if s.score >= MIN_SCORE and (s.matched_in_symptom >= needed or s.distinctive)
        ]
        # One common word that fits many symptoms ("my washer is noisy" -> sound, in ten rows) identifies
        # none of them; returning the first three would be a guess presented as an answer.
        if len(terms) == 1 and len(found) > MAX_MATCHES and not any(s.distinctive for s in found):
            return []
        return found

    def nearest_phrases(
        self,
        terms: list[str],
        manual_ids: set[str] | None = None,
        appliance_type: str | None = None,
        limit: int = MAX_NEAREST,
        negated: bool | None = None,
    ) -> list[str]:
        """The manual's own first phrase of the closest symptoms that share at least one word with the
        query but did not clear the matching rules -- a verbatim "did you mean", never a cause."""
        phrases: list[str] = []
        for s in self.score_all(terms, manual_ids, appliance_type, negated):
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
        g.negated = any(is_negated(p) for p in g.phrases)
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
    idf = {term: math.log(1 + n / df) for term, df in document_frequency.items()}
    symptom_df: dict[str, int] = {}
    for g in groups:
        for term in g.symptom_terms:
            symptom_df[term] = symptom_df.get(term, 0) + 1
    return SymptomIndex(groups=groups, idf=idf, spelling=Spelling(frozenset(idf)), symptom_df=symptom_df)


def load_symptom_index(path: Path | None = None) -> SymptomIndex:
    """Load data/index/symptoms.json. Call once at server startup, never per request."""
    path = path or DEFAULT_SYMPTOMS_PATH
    raw = json.loads(path.read_text())
    return build_index([SymptomRecord.model_validate(item) for item in raw])
