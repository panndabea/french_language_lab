"""Segment-level TRS parsing.

A TRS <Turn> can hold several <Sync time=...> markers (timestamps) and, for
multi-speaker turns, <Who nb="k"/> markers that switch to the k-th speaker in
the turn's `speaker` attribute. Each resulting segment is attributed to exactly
one speaker and flagged `overlap=True` if it came from a multi-speaker turn.
If the Who structure is malformed (text before first Who, nb out of range),
the whole turn is left unattributed (role 'overlap') instead of guessing.
"""
import re
from xml.etree import ElementTree as ET


def _clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def _turn_segments(turn, ids, roles, interview_id, turn_index):
    multi = len(ids) > 1
    cur_time = turn.attrib.get('startTime', '')
    cur_spk = None if multi else (ids[0] if ids else None)
    pieces = []  # (speaker_id, time, text)
    malformed = False

    def add(text):
        nonlocal malformed
        if not _clean(text):
            return
        if multi and cur_spk is None:
            malformed = True
        pieces.append([cur_spk, cur_time, text])

    add(turn.text)
    for el in turn:
        if el.tag == 'Sync':
            cur_time = el.attrib.get('time', cur_time)
        elif el.tag == 'Who' and multi:
            try:
                k = int(el.attrib.get('nb', ''))
            except ValueError:
                k = 0
            if 1 <= k <= len(ids):
                cur_spk = ids[k - 1]
            else:
                malformed = True
                cur_spk = None
        elif el.tag not in ('Who', 'Event', 'Comment', 'Background'):
            add(''.join(el.itertext()))
        add(el.tail)

    # merge consecutive pieces with same speaker and time
    merged = []
    for spk, t, txt in pieces:
        if merged and merged[-1][0] == spk and merged[-1][1] == t:
            merged[-1][2] += ' ' + txt
        else:
            merged.append([spk, t, txt])

    out = []
    for spk, t, txt in merged:
        if malformed:
            spk_id, role = ' '.join(ids), 'overlap'
        else:
            spk_id, role = spk, roles.get(spk, 'unknown')
        out.append({'interview_id': interview_id, 'turn_index': turn_index, 'speaker_id': spk_id,
                    'role': role, 'overlap': multi, 'start': t,
                    'turn_start': turn.attrib.get('startTime', ''), 'turn_end': turn.attrib.get('endTime', ''),
                    'text': _clean(txt)})
    return out


def parse_segments(content, interview_id):
    root = ET.fromstring(content)
    roles = {s.attrib['id']: s.attrib.get('name', 'unknown') for s in root.findall('.//Speaker')}
    segs = []
    idx = 0
    for turn in root.iter('Turn'):
        ids = turn.attrib.get('speaker', '').split()
        s = _turn_segments(turn, ids, roles, interview_id, idx)
        if s:
            segs.extend(s)
            idx += 1
    return segs
