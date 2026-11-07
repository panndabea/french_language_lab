"""Deterministic v2 predictor over speaker-attributed segments. Ground-truth blind.

Every decision is derived from cue records that quote a single source segment
verbatim, with speaker id, role, overlap flag and Sync timestamp. Unknown is the
default; conflicts produce unknown + status 'review_needed'.

Year handling: the task taxonomy {1970, 2005} is an unverified hypothesis.
- `cohort_hypothesis`: nearest cohort label (1970/2005/unknown) from era cues.
- `recording_year_lower_bound`: max present-anchored or past-referenced year.
- `interview_year` (strict): the cohort label only when no evidence contradicts it
  as a literal recording year; otherwise None with `out_of_domain_year_flag`.
"""
import re
from .frnum import find_years, find_ages, find_birth_years, parse_french_number, WORD_RUN

RULES_VERSION = 'rules_v2.5'

# ---- era cues (scored on all roles: interviewer questions also date the recording)
RECENT_LEXICAL = {
    'euro': (re.compile(r"\beuros?\b", re.I), 2),
    'internet': (re.compile(r"\binternet\b", re.I), 1),
    'sarkozy': (re.compile(r"\bsarkozy\b", re.I), 2),
    'mobile_phone': (re.compile(r"\btéléphones?\s+portables?\b|\bmon\s+portable\b", re.I), 1),
}
OLD_LEXICAL = {
    'nouveaux_francs': (re.compile(r"\bnouveaux\s+francs\b", re.I), 1),
    # contemporaneous naming (no year) of May 1968; '... mai soixante-huit' is retrospective in both eras -> 0
    'evenements_de_mai': (re.compile(r"\bévénements\s+de\s+mai\b(?!\s+(?:soixante|mille|dix-neuf|19|68))", re.I), 2),
    'marche_commun': (re.compile(r"\bmarché\s+commun\b", re.I), 1),
}
OLD_YEAR_PROFILE_MIN = 3   # >=3 distinct years mentioned, all <= 1972 -> weak old cue
PAST_MARK = re.compile(r"\b(?:depuis|j['’]\s*ai|j['’]\s*étais|était|avait|on\s+a|je\s+suis\s+(?:arrivée?|venue?|revenue?|partie?|entrée?)|dernier|dernière|il\s+y\s+a)\b", re.I)
FUTURE_MARK = re.compile(r"\b(?:va|vont|vais|prévu|prévue|sera|seront|aura|d['’]\s*ici|l['’]\s*an\s+deux\s+mille\b(?!\s+\w))", re.I)

# ---- gender cues: first-person agreement by interviewee; address by interviewer
F_AUDIBLE = r"contente|heureuse|veuve|ouvrière|infirmière|institutrice|directrice|vendeuse|coiffeuse|couturière|étudiante|enseignante|commerçante|certaine|seule\s+avec|femme\s+au\s+foyer"
M_AUDIBLE = r"content|heureux|veuf|ouvrier|infirmier|instituteur|directeur|vendeur|coiffeur|étudiant|enseignant|commerçant|certain"
F_ORTHO = r"née|mariée|allée|venue|arrivée|partie|sortie|restée|entrée|divorcée|retraitée|habituée|obligée|installée|née"
M_ORTHO = r"né|marié|allé|venu|arrivé|parti|sorti|resté|entré|divorcé|retraité|habitué|obligé|installé"
SELF = r"\b(?:je\s+suis|j['’]\s*étais|moi\s+j['’]\s*étais|je\s+serais|j['’]\s*ai\s+été)\s+(?:très\s+|pas\s+|bien\s+|tout\s+|toute\s+|plus\s+|un\s+peu\s+|assez\s+|vraiment\s+)*(?:une?\s+)?"
GENDER_CUES = [
    ('female', 'self_agreement_audible', 2.0, re.compile(SELF + r"(?:%s)\b" % F_AUDIBLE, re.I), 'interviewee'),
    ('male', 'self_agreement_audible', 2.0, re.compile(SELF + r"(?:%s)\b(?!e)" % M_AUDIBLE, re.I), 'interviewee'),
    ('female', 'self_agreement_orthographic', 1.0, re.compile(SELF + r"(?:%s)\b" % F_ORTHO, re.I), 'interviewee'),
    ('male', 'self_agreement_orthographic', 1.0, re.compile(SELF + r"(?:%s)(?![\wée])" % M_ORTHO, re.I), 'interviewee'),
    ('female', 'addressed_by_interviewer', 1.0, re.compile(r"(?<!\bla\s)(?<!\bune\s)(?<!\bcette\s)\b(?:madame|vous\s+êtes\s+(?:née|mariée|contente|arrivée|venue))\b", re.I), 'interviewer'),
    ('male', 'addressed_by_interviewer', 1.0, re.compile(r"(?<!\ble\s)(?<!\bun\s)(?<!\bce\s)(?<!\bdu\s)(?<!\bau\s)\b(?:monsieur|vous\s+êtes\s+(?:né|marié|content|arrivé|venu))(?![\wée])", re.I), 'interviewer'),
    ('female', 'relational_weak', 0.5, re.compile(r"\bmon\s+mari\b", re.I), 'interviewee'),
    ('male', 'relational_weak', 0.5, re.compile(r"\bma\s+femme\b", re.I), 'interviewee'),
]
MIN_PLAUSIBLE_SELF_AGE = 12  # 'j'ai deux ans' in context is usually a duration
GENDER_MIN_SCORE = 2.0
GENDER_MIN_RATIO = 3.0   # winner must outweigh loser 3:1

BIRTH_Q = re.compile(r"\bvous\s+êtes\s+née?\s+en\s+(?:l['’]\s*an\s+)?", re.I)
CONFIRM = re.compile(r"^\s*(?:oui|ouais|voilà|c['’]\s*est\s+ça|exactement|tout\s+à\s+fait|absolument)\b", re.I)
DENY = re.compile(r"^\s*(?:non|pas\s+du\s+tout|ah\s+non)\b", re.I)


def interviewer_birth_questions(segments):
    """'vous êtes né en quarante-sept ?' confirmed by the interviewee's next segment -> (year, q_seg, a_seg)."""
    out = []
    for k, s in enumerate(segments):
        if s['role'] != 'interviewer':
            continue
        m = BIRTH_Q.search(s['text'])
        if not m:
            continue
        rest = s['text'][m.end():]
        dm = re.match(r"\d{2,4}\b", rest)
        wm = WORD_RUN.match(rest)
        v = int(dm.group()) if dm else (parse_french_number(wm.group().strip(' -')) if wm else None)
        if v is None:
            continue
        if v < 100:
            v += 1900
        if not 1880 <= v <= 2015:
            continue
        nxt = next((t for t in segments[k + 1:k + 4] if t['role'] == 'interviewee'), None)
        if nxt and CONFIRM.match(nxt['text']) and not DENY.match(nxt['text']):
            out.append((v, s, nxt))
    return out


SPLIT_AGE_PREFIX = re.compile(r"(j['’]\s*ai|je\s+vais\s+avoir)\s*$", re.I)

COHORT_WINDOWS = {'1970': (1968, 1972), '2005': (2004, 2006)}
COHORT_RECORDING_RANGE = {'1970': (1968, 1972), '2005': (2005, 2015)}


def _ev(s, cue, value, weight=None, expr=None):
    e = {'cue': cue, 'value': value, 'quote': s['text'], 'speaker_id': s['speaker_id'], 'role': s['role'],
         'overlap': bool(s.get('overlap')), 'start': s['start'], 'turn_index': s.get('turn_index')}
    if weight is not None:
        e['weight'] = weight
    if expr is not None:
        e['expr'] = expr
    return e


def bracket(age):
    if age is None or age < 0 or age > 110:
        return None
    return f'{age // 10 * 10}-{age // 10 * 10 + 9}' if age < 90 else '90+'


def predict(interview_id, segments):
    ev = {'year': [], 'era_lexical': [], 'age': [], 'birth': [], 'gender': [], 'counter': []}
    recent_score = old_score = 0.0
    anchors, lower_bound_years, recent_years = [], [], set()
    all_years = set()
    others_present = any(s['role'] not in ('interviewer', 'interviewee', 'overlap') for s in segments)

    for s in segments:
        txt, role = s['text'], s['role']
        if role == 'overlap':
            continue  # unattributable
        # ---- years
        for y in find_years(txt):
            yr = y['year']
            all_years.add(yr)
            if y['present_anchor']:
                anchors.append(yr)
                ev['year'].append(_ev(s, 'present_anchor', yr, expr=y['expr']))
                lower_bound_years.append(yr)
            elif yr >= 1975 and yr != 2000:
                fut = bool(FUTURE_MARK.search(txt))
                past = bool(PAST_MARK.search(txt))
                ev['year'].append(_ev(s, 'year_mention_future' if fut else ('year_mention_past' if past else 'year_mention'), yr, expr=y['expr']))
                if yr >= 2001:
                    recent_years.add(yr)
                if past and not fut:
                    lower_bound_years.append(yr)
        for name, (rx, w) in RECENT_LEXICAL.items():
            if rx.search(txt) and not any(e['cue'] == name for e in ev['era_lexical']):
                recent_score += w
                ev['era_lexical'].append(_ev(s, name, 'recent', w))
        for name, (rx, w) in OLD_LEXICAL.items():
            if rx.search(txt) and not any(e['cue'] == name for e in ev['era_lexical']):
                old_score += w
                ev['era_lexical'].append(_ev(s, name, 'old', w))
        # ---- gender
        for g, cue, w, rx, need_role in GENDER_CUES:
            if role == need_role and rx.search(txt):
                if cue == 'addressed_by_interviewer' and others_present:
                    cue, w = 'addressed_by_interviewer_others_present', 0.5
                ev['gender'].append(_ev(s, cue, g, w, rx.search(txt).group()))
        if role != 'interviewee':
            continue
        # ---- age (interviewee only)
        for a in find_ages(txt):
            ev['age'].append(_ev(s, 'future_age_minus_1' if a['future'] else 'direct_age', a['age'], expr=a['expr']))
        for b in find_birth_years(txt):
            e = _ev(s, 'birth_year', b['year'], expr=b['expr'])
            e['candidates'] = b['candidates']
            ev['birth'].append(e)

    # ages split across consecutive interviewee segments: "je vais avoir" | "soixante et un an" (S001)
    for k in range(len(segments) - 1):
        a, b = segments[k], segments[k + 1]
        if a['role'] != 'interviewee' or b['role'] != 'interviewee':
            continue
        m = SPLIT_AGE_PREFIX.search(a['text'])
        if not m:
            continue
        for x in find_ages(m.group(1) + ' ' + b['text']):
            if x['start'] > len(m.group(1)) + 1:
                continue  # number must open the second segment
            e = _ev(b, 'future_age_minus_1' if x['future'] else 'direct_age', x['age'], expr=x['expr'])
            e['context_quote'] = a['text']
            e['context_start'] = a['start']
            ev['age'].append(e)

    for yr, q, ans in interviewer_birth_questions(segments):
        for seg_, cue in ((q, 'birth_year_interviewer_question_confirmed'), (ans, 'birth_year_confirmation')):
            e = _ev(seg_, cue, yr)
            e['candidates'] = [yr]
            ev['birth'].append(e)

    # ---- direct ages (validated before era decision: age + birth year dates the recording)
    ages_all = sorted({e['value'] for e in ev['age']})
    ages = []
    if ages_all:
        if min(ages_all) < MIN_PLAUSIBLE_SELF_AGE:
            ev['counter'].append({'cue': 'implausible_self_age_likely_duration', 'value': ages_all})
        elif max(ages_all) - min(ages_all) <= 2:
            ages = ages_all
        else:
            ev['counter'].append({'cue': 'conflicting_direct_ages', 'value': ages_all})
    # ---- birth-year candidates (two-digit years are century-ambiguous)
    cand_sets = [set(e['candidates']) for e in ev['birth']]
    birth_cands = sorted(set.intersection(*cand_sets)) if cand_sets else []
    if cand_sets and not birth_cands:
        ev['counter'].append({'cue': 'conflicting_birth_years', 'value': sorted({e['value'] for e in ev['birth']})})
    implied, resolved_birth = [], None
    if ages and birth_cands:
        feas = [c for c in birth_cands if 1960 <= c + max(ages) + 1 and c + min(ages) <= 2020]
        if len(feas) == 1:
            resolved_birth = feas[0]
            implied = [feas[0] + min(ages), feas[0] + max(ages) + 1]
            ev['year'].append({'cue': 'implied_recording_year_birth_plus_age', 'value': implied,
                               'birth_year': resolved_birth, 'ages': ages})
        elif not feas:
            ev['counter'].append({'cue': 'age_birth_inconsistent', 'value': {'ages': ages, 'births': birth_cands}})

    # ---- era decision
    if len(recent_years) >= 2:
        recent_score += 2
    elif len(recent_years) == 1:
        recent_score += 1
    if len(all_years) >= OLD_YEAR_PROFILE_MIN and max(all_years) <= 1972:
        old_score += 1
        ev['era_lexical'].append({'cue': 'old_year_profile', 'value': sorted(all_years)})
    for a in anchors:
        if a >= 1995:
            recent_score += 3
        elif 1960 <= a <= 1975:
            old_score += 3
    if implied:
        if 1960 <= implied[0] and implied[1] <= 1975:
            old_score += 3
        elif implied[0] >= 1995:
            recent_score += 3
            lower_bound_years.append(implied[0])
    lower_bound = max(lower_bound_years) if lower_bound_years else None
    if lower_bound and lower_bound >= 1980:
        recent_score += 1

    if recent_score >= 2 and old_score == 0:
        cohort = '2005'
    elif old_score >= 2 and recent_score == 0:
        cohort = '1970'
    else:
        cohort = 'unknown'
    era_conflict = recent_score > 0 and old_score > 0

    out_of_domain = False
    if lower_bound and lower_bound > COHORT_WINDOWS['2005'][1]:
        out_of_domain = True
    for a in anchors:
        if not any(lo <= a <= hi for lo, hi in COHORT_WINDOWS.values()):
            out_of_domain = True
    if implied and not any(implied[0] <= hi and lo <= implied[1] for lo, hi in COHORT_WINDOWS.values()):
        out_of_domain = True
    strict_year = None
    if cohort != 'unknown' and not out_of_domain:
        strict_year = cohort

    # ---- recording-year interval for age-from-birth computation
    if anchors and len(set(anchors)) == 1:
        rec_range = (anchors[0], anchors[0])
    elif cohort != 'unknown':
        lo, hi = COHORT_RECORDING_RANGE[cohort]
        if lower_bound and cohort == '2005':
            lo = max(lo, lower_bound)
            hi = max(hi, lo)
        rec_range = (lo, hi)
    else:
        rec_range = None

    # ---- age decision
    age_bracket, age_range, age_basis = None, None, None
    births = birth_cands
    if ages:
        age_bracket, age_range, age_basis = bracket(min(ages)), (min(ages), max(ages)), 'direct_age'
        if bracket(max(ages)) != age_bracket:
            age_bracket = None
    elif births and rec_range:
        feas = [c for c in births if rec_range[0] - c - 1 >= 0 and rec_range[1] - c <= 110]
        if len(feas) == 1:
            lo_age, hi_age = rec_range[0] - feas[0] - 1, rec_range[1] - feas[0]
            age_range, age_basis = (lo_age, hi_age), 'birth_year_plus_recording_range'
            if bracket(lo_age) == bracket(hi_age):
                age_bracket = bracket(lo_age)
    low_conf_age = bool(ages_all) and min(ages_all) < 15

    # ---- gender decision
    score = {'female': 0.0, 'male': 0.0}
    for e in ev['gender']:
        score[e['value']] += e['weight']
    win = max(score, key=score.get)
    lose = 'male' if win == 'female' else 'female'
    non_rel = sum(e['weight'] for e in ev['gender'] if e['value'] == win
                  and e['cue'] not in ('relational_weak', 'addressed_by_interviewer_others_present'))
    if score[win] >= GENDER_MIN_SCORE and non_rel >= 1.0 and score[win] >= GENDER_MIN_RATIO * score[lose]:
        gender = win
    else:
        gender = 'unknown'
    gender_conflict = score['female'] > 0 and score['male'] > 0

    status = 'review_needed' if (era_conflict or out_of_domain or ev['counter'] or low_conf_age
                                 or (gender_conflict and gender == 'unknown')) else 'rules'

    # cap evidence lists for readability but record totals
    counts = {k: len(v) for k, v in ev.items()}
    for k in ev:
        ev[k] = ev[k][:8]
    return {
        'interview_id': interview_id, 'rules_version': RULES_VERSION,
        'age_bracket': age_bracket, 'age_range_estimate': list(age_range) if age_range else None, 'age_basis': age_basis,
        'gender': gender, 'gender_scores': score,
        'interview_year': strict_year, 'cohort_hypothesis': cohort,
        'era_scores': {'recent': recent_score, 'old': old_score},
        'recording_year_lower_bound': lower_bound, 'implied_recording_years': implied, 'present_anchor_years': sorted(set(anchors)),
        'out_of_domain_year_flag': out_of_domain, 'status': status,
        'evidence_counts': counts, 'evidence': ev,
    }
