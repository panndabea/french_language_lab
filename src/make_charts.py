"""Publication charts from frozen predictions + post-freeze evaluation. Light mode, validated palette slots 1-3.

    .venv/bin/python -m src.make_charts --ground-truth ~/Downloads/impactLab/lab_blind_speakers.tsv
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'   # validated: all-pairs CVD ΔE ≥ 9.2 (light)
plt.rcParams.update({'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
                     'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2,
                     'xtick.color': INK2, 'ytick.color': INK2, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'axes.grid.axis': 'y', 'grid.color': GRID, 'grid.linewidth': 0.6,
                     'axes.titlesize': 11, 'axes.titleweight': 'bold', 'axes.titlecolor': INK, 'axes.titlelocation': 'left'})


def _bars(ax, x, h, color, labels, width):
    bars = ax.bar(x, h, width=width, color=color, edgecolor=SURFACE, linewidth=2, zorder=2)
    for b, lab in zip(bars, labels):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.015, lab, ha='center', va='bottom', fontsize=8.5, color=INK)
    return bars


def fig_llm_vs_rules(E, out):
    fields = [('gender', 'Gender'), ('age_bracket', 'Age bracket'), ('cohort_hypothesis', 'Wave (1970/2005)')]
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    for ax, metric, title in ((axes[0], 'coverage', 'Coverage (share answered)'),
                              (axes[1], 'accuracy_when_answered', 'Accuracy when answered')):
        for k, (who, color, dx) in enumerate((('llm', BLUE, -0.2), ('rules', ORANGE, 0.2))):
            ms = [E[f]['paired_on_llm_subset'][who] for f, _ in fields]
            vals = [m[metric] or 0 for m in ms]
            labs = [f'{v:.0%}\n({m["answered"]}/{m["n_gold"]})' if metric == 'coverage' else f'{v:.0%}\n(n={m["answered"]})'
                    for v, m in zip(vals, ms)]
            _bars(ax, [i + dx for i in range(3)], vals, color, labs, 0.38)
        ax.set_xticks(range(3), [n for _, n in fields])
        ax.set_ylim(0, 1.28)
        ax.set_yticks([0, .25, .5, .75, 1], ['0%', '25%', '50%', '75%', '100%'])
        ax.set_title(title)
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
               labels=['LLM research loop', 'Deterministic rules'], frameon=False, loc='lower center', ncol=2, fontsize=9)
    fig.suptitle('Same 99 interviews (LLM-completed subset): LLM loop vs deterministic rules', x=0.01, ha='left',
                 fontsize=10, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out / 'fig1_llm_vs_rules.png', dpi=200)
    plt.close(fig)


def fig_age_errors(E, out):
    d = E['age_bracket']['paired_on_llm_subset']['llm']['bin_error_distribution']
    xs = [-2, -1, 0, 1, 2]
    vals = [d.get(str(x), 0) for x in xs]
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    colors = [BLUE if x == 0 else ORANGE for x in xs]
    bars = ax.bar(xs, vals, color=colors, edgecolor=SURFACE, linewidth=2, width=0.7, zorder=2)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.8, str(v), ha='center', fontsize=9, color=INK)
    ax.set_xticks(xs, ['−2 bins', '−1 bin\n(too young)', 'exact', '+1 bin\n(too old)', '+2 bins'])
    ax.set_ylabel('interviews')
    ax.set_ylim(0, max(vals) * 1.2)
    fig.text(0.01, 0.95, 'LLM age-bracket error (n=68 answered)', fontsize=11, fontweight='bold', color=INK)
    fig.text(0.01, 0.89, 'All 9 errors are off by exactly one bracket', fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(out / 'fig2_age_error_distribution.png', dpi=200)
    plt.close(fig)


def fig_confidence(E, out):
    bc = E['age_bracket']['by_confidence']
    order = [c for c in ('high', 'medium', 'low') if c in bc]
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    vals = [bc[c]['accuracy_when_answered'] for c in order]
    labs = [f'{v:.0%}\n({bc[c]["correct"]}/{bc[c]["answered"]})' for v, c in zip(vals, order)]
    _bars(ax, range(len(order)), vals, BLUE, labs, 0.55)
    ax.set_xticks(range(len(order)), [f'{c}\n(abstained {bc[c]["abstained"]})' for c in order])
    ax.set_ylim(0, 1.25)
    ax.set_yticks([0, .25, .5, .75, 1], ['0%', '25%', '50%', '75%', '100%'])
    ax.set_title('LLM age accuracy by self-reported confidence')
    fig.tight_layout()
    fig.savefig(out / 'fig3_age_accuracy_by_confidence.png', dpi=200)
    plt.close(fig)


def fig_recording_years(gt, out):
    ev = json.loads(Path('evidence_frozen.json').read_text(encoding='utf-8'))
    years = {e['interview_id']: (e.get('decision') or {}).get('recording_year_estimate') for e in ev if e['source'] == 'llm'}
    by = {'ESLO1': Counter(), 'ESLO2': Counter()}
    for i, y in years.items():
        if y:
            by[gt[i]['wave']][y] += 1
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for wave, color in (('ESLO1', BLUE), ('ESLO2', ORANGE)):
        ys = sorted(by[wave])
        ax.bar([str(y) for y in ys], [by[wave][y] for y in ys], color=color, edgecolor=SURFACE, linewidth=2,
               label=f'{wave} (gold wave), n={sum(by[wave].values())}', zorder=2)
    ax.set_ylabel('interviews')
    ax.legend(frameon=False, fontsize=8.5)
    fig.text(0.01, 0.95, 'LLM-estimated recording year, by gold wave', fontsize=11, fontweight='bold', color=INK)
    fig.text(0.01, 0.89, 'The nominal "2005" wave (ESLO2) was recorded ≈2008–2012', fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(out / 'fig4_recording_year_by_wave.png', dpi=200)
    plt.close(fig)


def fig_cost(out):
    ct = json.loads(Path('outputs/llm_full/cost_time.json').read_text())
    costs = [c for _, c in ct['per_interview_cost'] if c > 0]
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.hist(costs, bins=[i / 20 for i in range(0, 21)], color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=2)
    med = sorted(costs)[len(costs) // 2]
    ax.axvline(med, color=INK2, linewidth=1, linestyle='--')
    ax.text(med + 0.01, ax.get_ylim()[1] * 0.92, f'median ${med:.2f}', color=INK2, fontsize=8.5)
    ax.set_xlabel('API cost per interview (USD, Opus 5.5 list price)')
    ax.set_ylabel('interviews')
    ax.set_title(f'Cost per newly processed interview (n={len(costs)})')
    fig.tight_layout()
    fig.savefig(out / 'fig5_cost_per_interview.png', dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ground-truth', required=True)
    ap.add_argument('--out', default='figures')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    E = json.loads(Path('evaluation/evaluation.json').read_text(encoding='utf-8'))
    gt = {r['blind_id']: r for r in csv.DictReader(open(Path(a.ground_truth).expanduser(), encoding='utf-8-sig'), delimiter='\t')}
    fig_llm_vs_rules(E, out)
    fig_age_errors(E, out)
    fig_confidence(E, out)
    fig_recording_years(gt, out)
    fig_cost(out)
    print(sorted(p.name for p in out.glob('*.png')))


if __name__ == '__main__':
    main()
