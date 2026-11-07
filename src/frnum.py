"""Deterministic French number-word parsing for years and self-reported ages.

Transcripts write numbers orthographically ("deux mille dix"), so digit-only
regexes miss nearly everything. Matches are *candidate* evidence only.
"""
import re

UNITS = {'zéro': 0, 'un': 1, 'une': 1, 'deux': 2, 'trois': 3, 'quatre': 4, 'cinq': 5, 'six': 6, 'sept': 7,
         'huit': 8, 'neuf': 9, 'dix': 10, 'onze': 11, 'douze': 12, 'treize': 13, 'quatorze': 14,
         'quinze': 15, 'seize': 16}
TENS = {'vingt': 20, 'vingts': 20, 'trente': 30, 'quarante': 40, 'cinquante': 50, 'soixante': 60,
        'septante': 70, 'huitante': 80, 'octante': 80, 'nonante': 90}
NUMWORDS = set(UNITS) | set(TENS) | {'cent', 'cents', 'mille', 'mil', 'et'}

TOKEN = re.compile(r"[a-zàâçéèêëîïôûùüÿœ]+|\d+|['’]", re.I)
WORD_RUN = re.compile(r"\b(?:(?:%s)(?:[\s-]+|$))+" % '|'.join(sorted(NUMWORDS, key=len, reverse=True)), re.I)

# words after a number that signal a quantity, not a calendar year
QUANTITY_NOUNS = re.compile(
    r"^\s*(?:euros?|francs?|balles|personnes?|habitants?|gens|mètres?|km|kilomètres?|hectares?|ans|années|"
    r"kilos?|tonnes?|fois|élèves|ouvriers|logements|maisons|litres?|heures?|jours?|mois|places|morts|"
    r"salariés|employés|nouveaux|anciens|francs|centimes|pieds|membres|adhérents)\b", re.I)
PRESENT_ANCHOR = re.compile(
    r"(?:on\s+est|nous\s+sommes|on\s+se\s+trouve|maintenant\s+on\s+est|aujourd['’]\s*hui\s+on\s+est)\s+(?:en\s+|au\s+)?(?:l['’]\s*an\s+)?$"
    r"|cette\s+année\s*(?:,|en)?\s*$", re.I)


def parse_french_number(s):
    toks = [t for t in re.split(r"[\s-]+", s.lower().strip()) if t]
    if not toks or any(t not in NUMWORDS for t in toks) or toks[0] == 'et' or toks[-1] == 'et':
        return None
    total, cur, prev = 0, 0, None
    for t in toks:
        if t == 'et':
            pass
        elif t in UNITS:
            cur += UNITS[t]
        elif t in TENS:
            if t.startswith('vingt') and prev == 'quatre':
                cur += 80 - 4
            else:
                cur += TENS[t]
        elif t in ('cent', 'cents'):
            cur = (cur or 1) * 100
        elif t in ('mille', 'mil'):
            total += (cur or 1) * 1000
            cur = 0
        prev = t
    return total + cur


def _runs(text):
    """Yield (start, end, value, is_digit) for number expressions in text."""
    for m in re.finditer(r"\b\d{1,4}\b", text):
        yield m.start(), m.end(), int(m.group()), True
    for m in WORD_RUN.finditer(text):
        span = m.group().rstrip(' -')
        # strip leading/trailing 'et'
        span_s = re.sub(r"^(?:et[\s-]+)+", '', span, flags=re.I)
        start = m.start() + (len(span) - len(span_s))
        span_s = re.sub(r"(?:[\s-]+et)+$", '', span_s, flags=re.I)
        v = parse_french_number(span_s)
        if v is not None:
            yield start, start + len(span_s), v, False


def find_years(text, lo=1900, hi=2030):
    out = []
    for s, e, v, is_digit in sorted(_runs(text)):
        if not lo <= v <= hi:
            continue
        expr = text[s:e].lower()
        if not is_digit and not re.search(r"\b(?:mille|mil|cents?)\b", expr):
            continue
        if QUANTITY_NOUNS.match(text[e:]):
            continue
        before = text[max(0, s - 40):s]
        out.append({'year': v, 'expr': text[s:e], 'start': s,
                    'present_anchor': bool(PRESENT_ANCHOR.search(before))})
    return out


AGE_PREFIX = re.compile(r"(?:\bj['’]\s*ai|\bje\s+suis\s+âgée?\s+de|\bje\s+vais\s+avoir)\s+$", re.I)
NARRATIVE = re.compile(r"\b(?:quand|lorsque|si|où|comme|depuis\s+que|dès\s+que|avant\s+que|après\s+que)\s+(?:moi\s+)?$", re.I)


def find_ages(text):
    out = []
    for s, e, v, is_digit in sorted(_runs(text)):
        if not re.match(r"\s*ans?\b", text[e:], re.I):
            continue
        before = text[max(0, s - 40):s]
        m = AGE_PREFIX.search(before)
        if not m:
            continue
        # durations: "j'ai trente ans de métier", "j'ai vingt ans que..."
        if re.match(r"\s*ans?\s+(?:de\b|d['’]|que\b|qu['’])", text[e:], re.I):
            continue
        if NARRATIVE.search(before[:m.start()]):
            continue
        future = bool(re.search(r"vais\s+avoir\s+$", m.group(), re.I))
        if future:
            v -= 1  # "je vais avoir 91 ans" -> currently 90
        if 0 < v <= 110:
            out.append({'age': v, 'expr': text[s:e], 'start': s, 'future': future})
    return out


BIRTH_PREFIX = re.compile(
    r"\b(?:je\s+suis|j['’]\s*y\s+suis)\s+(née?\s+en|de)\s+(?:l['’]\s*an\s+)?", re.I)
MONTH_AFTER = re.compile(r"^\s*(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b", re.I)
EARLIEST_BIRTH = 1875


def find_birth_years(text):
    """First-person birth year: 'je suis né(e) en 1932', 'je suis né en quarante et un',
    "j'y suis née en mille neuf cent vingt neuf", 'je suis de quarante'.
    Two-digit years are century-ambiguous: `candidates` lists 18xx (if >= 1875) and 19xx;
    `year` is the 19xx default. Callers must resolve with age or cohort feasibility."""
    out = []
    for m in BIRTH_PREFIX.finditer(text):
        rest = text[m.end():]
        dm = re.match(r"(\d{2}|\d{4})\b", rest)
        wm = WORD_RUN.match(rest)
        if dm:
            expr, v = dm.group(), int(dm.group())
        elif wm:
            expr = re.sub(r"(?:[\s-]+et)+$", '', wm.group().rstrip(' -'), flags=re.I)
            v = parse_french_number(expr)
        else:
            continue
        after = rest[len(expr):]
        if v is None or QUANTITY_NOUNS.match(after) or MONTH_AFTER.match(after):
            continue
        if 10 <= v <= 99:
            cands = [c for c in (1800 + v, 1900 + v) if c >= EARLIEST_BIRTH]
        elif 1875 <= v <= 2015:
            cands = [v]
        else:
            continue
        g = m.group(1).lower()
        out.append({'year': cands[-1], 'candidates': cands, 'expr': expr, 'start': m.end(),
                    'grammar': 'female' if g.startswith('née') else ('male' if g.startswith('né') else None)})
    return out
