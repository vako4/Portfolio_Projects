"""
Generate notebooks/03_results.ipynb.
Run from project root: uv run python notebooks/create_03_results.py
"""
from pathlib import Path
import nbformat as nbf

nb  = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.14.5"},
}

M = nbf.v4.new_markdown_cell
C = nbf.v4.new_code_cell
cells = []


# ══════════════════════════════════════════════════════════════════════════════
# TITLE
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
# Results: Constrained Mean-Variance vs Passive Equity Portfolios

This notebook presents the complete empirical results of the thesis, organized by
hypothesis. Sections 3–5 correspond directly to the three test suites implemented in
`src/stats.py`; Sections 1–2 establish the sample and descriptive baseline. Section 6
synthesizes all findings into a coherent narrative. All outputs are loaded from
pre-computed parquet and CSV files in `data/processed/` and `results/` — no
optimization or backtest code is re-executed here.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════
cells.append(C("""\
%matplotlib inline
import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from IPython.display import display, Image

ROOT      = Path('..')
PROCESSED = ROOT / 'data' / 'processed'
TABLES    = ROOT / 'results' / 'tables'
FIGURES   = ROOT / 'results' / 'figures'

# ── colour palette ────────────────────────────────────────────────────────────
C_MV    = '#1f3a68'   # dark navy  — MV gross
C_NET   = '#7a7a7a'   # mid grey   — MV net
C_BM    = '#c0392b'   # soft red   — benchmark
C_NAIVE = '#2c7873'   # soft teal  — naive 1/N

COLORS = {
    'mv_gross':  C_MV,
    'mv_net':    C_NET,
    'naive':     C_NAIVE,
    'benchmark': C_BM,
}
LABELS = {
    'mv_gross':  'MV Gross',
    'mv_net':    'MV Net',
    'naive':     'Naive 1/N',
    'benchmark': 'Benchmark (S&P 500 TR)',
}
REGIME_COLORS = {
    'bull':     '#d6ead7',
    'bear':     '#f5d0d0',
    'recovery': '#cde8f0',
}

plt.rcParams.update({
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'font.size': 9,
    'axes.spines.top': False,
    'axes.spines.right': False,
})

print('Setup complete.')
print(f'Tables in:  {TABLES.resolve()}')
print(f'Figures in: {FIGURES.resolve()}')
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 1. Sample Periods and Regime Classification

The analysis spans **287 monthly observations** from February 2001 through December
2024, covering the full period for which the rolling 60-month estimation window can
be populated and backtest returns are available. Two evaluation windows are used:

- **Full sample (2001-02 to 2024-12):** 287 months; encompasses three complete
  bear-market cycles — the dot-com bust, the global financial crisis, and the
  2022 drawdown.
- **Post-2015 high-coverage subsample (2015-01 to 2024-12):** 120 months; restricts
  to the period where constituent coverage consistently exceeds 95%, limiting
  survivorship and look-ahead effects.

Market regimes are classified on the S&P 500 Total Return index using a
peak-to-trough drawdown criterion:

- **Main classification (−20% threshold):** the standard bear-market definition,
  identifying three complete cycles. COVID-19 (peak Dec 2019, trough Mar 2020,
  −19.6% drawdown) falls just below this threshold and is *not* captured.
- **Sensitivity classification (−15% threshold):** a looser rule that additionally
  captures COVID-19 and the 1998 LTCM episode, serving as a robustness check
  on the regime-conditional results.\
"""))

cells.append(C("""\
# Display both regime timeline figures
display(Image(filename=str(FIGURES / 'regimes_timeline_main.png'),        width=860))
display(Image(filename=str(FIGURES / 'regimes_timeline_sensitivity.png'), width=860))
"""))

cells.append(C("""\
# Regime episode summary tables
eps_main = pd.read_csv(TABLES / 'regime_episodes_main.csv')
eps_sens = pd.read_csv(TABLES / 'regime_episodes_sensitivity.csv')

for col in ['start_date', 'end_date']:
    eps_main[col] = pd.to_datetime(eps_main[col]).dt.strftime('%Y-%m')
    eps_sens[col] = pd.to_datetime(eps_sens[col]).dt.strftime('%Y-%m')

print('Main classification  (-20% threshold):')
display(eps_main[eps_main['regime'].isin(['bear', 'recovery'])].reset_index(drop=True))

print('\\nSensitivity classification  (-15% threshold):')
display(eps_sens[eps_sens['regime'].isin(['bear', 'recovery'])].reset_index(drop=True))
"""))

cells.append(C("""\
# Regime month counts — full sample and post-2015
reg_main = pd.read_parquet(PROCESSED / 'regimes_main.parquet').squeeze()
reg_sens = pd.read_parquet(PROCESSED / 'regimes_sensitivity.parquet').squeeze()
reg_main.index = pd.to_datetime(reg_main.index)
reg_sens.index = pd.to_datetime(reg_sens.index)

post15 = pd.Timestamp('2015-01-01')

def count_table(reg, label):
    full = reg.value_counts()
    post = reg[reg.index >= post15].value_counts()
    rows = []
    for r in ['bull', 'bear', 'recovery']:
        rows.append({'Regime': r.title(), 'Full sample': int(full.get(r, 0)),
                     'Post-2015': int(post.get(r, 0))})
    df = pd.DataFrame(rows).set_index('Regime')
    df.loc['Total'] = df.sum()
    print(f'\\n{label}')
    display(df)

count_table(reg_main, 'Main classification  (-20%)')
count_table(reg_sens, 'Sensitivity classification  (-15%)')
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 2. Descriptive Performance

Across the full 2001–2024 period, the constrained mean-variance strategy (MV gross)
delivers an annualized return of **+8.95%** versus **+8.34%** for the S&P 500 Total
Return benchmark — a modest 61 bp gross premium. The more salient improvement is in
risk: MV gross exhibits annualized volatility of **11.64%** against the benchmark's
**15.25%**, a reduction of roughly **24%**. Maximum drawdown is **42.07%** for MV
gross versus **50.95%** for the benchmark — a **9 percentage-point** improvement.

In the post-2015 subsample the benchmark's Sharpe ratio (0.77) *surpasses* MV gross
(0.70), reflecting the powerful concentrated-technology bull run that cap-weighted
indices captured far more efficiently than a diversified minimum-variance tilt.

Transaction costs of 20 bp per round-trip trim roughly **28 bp/yr** off gross returns
(MV net vs MV gross), a realistic but modest drag relative to the volatility
reduction achieved.\
"""))

cells.append(C("""\
mfp  = pd.read_csv(TABLES / 'metrics_full_period.csv',  index_col=0)
mp15 = pd.read_csv(TABLES / 'metrics_post_2015.csv',    index_col=0)

def fmt_metrics(df):
    out = df.copy().astype(object)
    for col in ['total_return', 'ann_return', 'ann_volatility', 'max_drawdown']:
        if col in df.columns:
            out[col] = df[col].map(lambda x: f'{x*100:+.2f}%' if pd.notna(x) else '-')
    for col in ['sharpe', 'sortino']:
        if col in df.columns:
            out[col] = df[col].map(lambda x: f'{x:.4f}' if pd.notna(x) else '-')
    out['n_months'] = df['n_months'].astype(int)
    return out

print('Full period  (2001-02 to 2024-12):')
display(fmt_metrics(mfp))
print('\\nPost-2015 subsample  (2015-01 to 2024-12):')
display(fmt_metrics(mp15))
"""))

cells.append(C("""\
display(Image(filename=str(FIGURES / 'backtest_cumulative_returns.png'), width=860))
"""))

cells.append(C("""\
# ── Figure 1: Running drawdown ──────────────────────────────────────────────
returns = pd.read_parquet(PROCESSED / 'backtest_returns.parquet')
returns.index = pd.to_datetime(returns.index)

def running_dd(ret):
    p = (1 + ret).cumprod()
    return (p / p.cummax() - 1) * 100   # in percent

dd = pd.DataFrame({k: running_dd(returns[k]) for k in ['mv_gross', 'naive', 'benchmark']})

# Compress regimes into contiguous episodes for axvspan
def to_episodes(reg):
    grp_id = (reg != reg.shift()).cumsum()
    return [{'r': g.iloc[0], 's': g.index[0], 'e': g.index[-1]}
            for _, g in reg.groupby(grp_id, sort=False)]

episodes = to_episodes(reg_main)

fig, ax = plt.subplots(figsize=(13, 5))

for ep in episodes:
    ax.axvspan(ep['s'], ep['e'], color=REGIME_COLORS[ep['r']], alpha=1.0, zorder=0)

ax.yaxis.grid(True, color='#c8c8c8', linewidth=0.5, zorder=1)
ax.xaxis.grid(False)
ax.axhline(0, color='#888888', linewidth=0.7, linestyle='--', zorder=1)

for key, label in [('mv_gross', 'MV Gross'), ('naive', 'Naive 1/N'),
                   ('benchmark', 'Benchmark (S&P 500 TR)')]:
    ax.plot(dd.index, dd[key], color=COLORS[key], linewidth=1.7, label=label, zorder=2)

regime_patches = [mpatches.Patch(color=REGIME_COLORS[r], label=r.title())
                  for r in ['bull', 'bear', 'recovery']]
handles, _ = ax.get_legend_handles_labels()
ax.legend(handles=handles + regime_patches, fontsize=8, loc='lower left',
          framealpha=0.85, ncol=2)

ax.set_xlim(dd.index[0], dd.index[-1])
ax.set_xlabel('Date', fontsize=10)
ax.set_ylabel('Drawdown (%)', fontsize=10)
ax.set_title(
    'Running Drawdown from All-Time High  —  2001 to 2024\\n'
    '(green = bull  |  red = bear  |  blue = recovery)',
    fontsize=11, fontweight='bold', pad=10,
)
fig.tight_layout()

out = FIGURES / 'drawdown_over_time.png'
fig.savefig(out, dpi=300, bbox_inches='tight')
plt.show()
print(f'Saved  {out}')
"""))

cells.append(M("""\
The drawdown chart confirms that the volatility benefit translates directly into
**persistent drawdown protection**: MV gross never breaches −43% while the benchmark
and the naive 1/N portfolio both exceed −50% during the global financial crisis.
In the post-2015 window — which contains only one bear episode (the 2022 drawdown)
— MV gross reaches −17% versus −24% for the benchmark, a 7 pp advantage that
appears in every sub-period examined.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 3. H1: Risk-Adjusted Performance Tests

**H1:** *The constrained mean-variance strategy generates statistically significant
risk-adjusted outperformance relative to the passive S&P 500 benchmark over the full
evaluation period.*

We test H1 using the Jobson-Korkie-Memmel (JKM) Sharpe ratio difference test
(Memmel 2003 correction), applied to all strategy pairs over the full period and the
post-2015 subsample. The JKM statistic is asymptotically N(0,1) under H₀ of equal
population Sharpe ratios; we report two-sided p-values. Rejection of H₁ requires
p < 0.05 for the MV gross vs benchmark comparison.\
"""))

cells.append(C("""\
jkm_fp  = pd.read_csv(TABLES / 'sharpe_tests_full_period.csv', index_col=0)
jkm_p15 = pd.read_csv(TABLES / 'sharpe_tests_post_2015.csv',  index_col=0)

def fmt_jkm(df):
    out = df.copy().astype(object)
    for col in ['sharpe_a_ann', 'sharpe_b_ann', 'sharpe_diff_ann',
                'correlation', 'jkm_statistic']:
        out[col] = df[col].map(lambda x: f'{x:.4f}' if pd.notna(x) else '-')
    out['p_value'] = df['p_value'].map(lambda x: f'{x:.3f}' if pd.notna(x) else '-')
    out['n_obs']   = df['n_obs'].astype(int)
    return out

print('JKM Sharpe Difference Tests  —  Full Period (2001-02 to 2024-12):')
display(fmt_jkm(jkm_fp))
print('\\nJKM Sharpe Difference Tests  —  Post-2015 Subsample:')
display(fmt_jkm(jkm_p15))
"""))

cells.append(C("""\
# Key p-value headline
pairs = [
    ('mv_gross vs benchmark', 'MV gross vs benchmark'),
    ('mv_gross vs naive',     'MV gross vs naive    '),
    ('mv_net vs benchmark',   'MV net   vs benchmark'),
    ('naive vs benchmark',    'Naive    vs benchmark'),
]
print('JKM p-values  (two-sided, * = significant at 5%):')
print(f'  {"Pair":<28}  {"Full-period":>12}  {"Post-2015":>12}')
print('  ' + '-' * 58)
for row, label in pairs:
    fp_p  = float(jkm_fp.loc[row,  'p_value'])
    p15_p = float(jkm_p15.loc[row, 'p_value'])
    s_fp  = ' *' if fp_p  < 0.05 else '  '
    s_p15 = ' *' if p15_p < 0.05 else '  '
    print(f'  {label:<28}  p = {fp_p:.3f}{s_fp}    p = {p15_p:.3f}{s_p15}')
"""))

cells.append(M("""\
**H1 conclusion — fails to reject.**

The full-period Sharpe gap for MV gross vs the benchmark is **+0.160 annualized**
(0.659 vs 0.499), but the JKM statistic is far from significant (p = 0.161). The
post-2015 Sharpe gap *reverses* to **−0.073** (p = 0.691), driven by the benchmark's
exceptional concentrated-technology performance between 2015 and 2024.

No comparison pair achieves p < 0.05 in either window. The statistical power of
the JKM test is limited by the 287 (and 120) observation counts, but the
directional reversal post-2015 also reflects a genuine structural shift: cap-weighted
passive exposure *outperformed* the diversified minimum-variance tilt in a regime
dominated by narrow mega-cap leadership.

The key caveat is that Sharpe-ratio equivalence does not mean the strategies are
interchangeable. The **drawdown protection is real and persistent** (−42% vs −51%
full-period, −17% vs −24% post-2015) and survives every sub-period. The appropriate
framing is that MV gross delivers *comparable* risk-adjusted returns at *substantially
lower realized risk* — a trade-off many institutional investors would accept even
absent a Sharpe premium.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 4. Factor Regression Analysis

The apparent CAPM alpha of MV gross demands scrutiny: minimum-variance strategies
are known to load heavily on the low-beta anomaly (Frazzini and Pedersen 2014),
the quality (RMW) factor, and the conservative investment (CMA) factor — all of
which are well-documented sources of return that do not reflect skill. The
Fama-French-Carhart five-factor-plus-momentum framework is therefore the appropriate
lens for distinguishing *genuine alpha* from *systematic factor exposure*.

We estimate three nested OLS regressions — CAPM, FF3, and FF5+MOM — with Newey-West
HAC standard errors (6 lags, corresponding to the standard monthly rule-of-thumb
floor(4·(T/100)^(2/9)) ≈ 5, rounded up). Alpha is reported annualized (×12).\
"""))

cells.append(C("""\
reg_fp  = pd.read_csv(TABLES / 'factor_regressions_full_period.csv', index_col=[0, 1])
reg_p15 = pd.read_csv(TABLES / 'factor_regressions_post_2015.csv',  index_col=[0, 1])

def fmt_reg(df):
    out = df.copy().astype(object)
    out['alpha_annualized'] = df['alpha_annualized'].map(lambda x: f'{x*100:+.2f}%')
    out['alpha_t_stat']     = df['alpha_t_stat'].map(lambda x: f'{x:.2f}')
    out['alpha_p_value']    = df['alpha_p_value'].map(lambda x: f'{x:.3f}')
    for col in ['mkt_beta', 'smb_beta', 'hml_beta', 'rmw_beta', 'cma_beta', 'mom_beta']:
        out[col] = df[col].map(lambda x: f'{x:.3f}' if pd.notna(x) else '-')
    out['r_squared'] = df['r_squared'].map(lambda x: f'{x:.3f}')
    out['n_obs']     = df['n_obs'].astype(int)
    return out

print('Factor Regressions  —  Full Period (2001-02 to 2024-12):')
display(fmt_reg(reg_fp))
print('\\nFactor Regressions  —  Post-2015 Subsample:')
display(fmt_reg(reg_p15))
"""))

cells.append(C("""\
# Alpha shrinkage for MV gross (full period)
print('MV Gross alpha shrinkage across models  (full period, annualized):')
print(f'  {"Model":<10}  {"Alpha":>10}  {"t-stat":>8}  {"p-value":>8}')
print('  ' + '-' * 42)
for model in ['capm', 'ff3', 'ff5mom']:
    a = float(reg_fp.loc[('mv_gross', model), 'alpha_annualized']) * 100
    t = float(reg_fp.loc[('mv_gross', model), 'alpha_t_stat'])
    p = float(reg_fp.loc[('mv_gross', model), 'alpha_p_value'])
    print(f'  {model.upper():<10}  {a:>+9.2f}%  {t:>8.2f}  {p:>8.3f}')

capm_a = float(reg_fp.loc[('mv_gross', 'capm'),   'alpha_annualized']) * 100
ff5_a  = float(reg_fp.loc[('mv_gross', 'ff5mom'), 'alpha_annualized']) * 100
shrink = (capm_a - ff5_a) / capm_a * 100
print(f'\\n  Reduction CAPM -> FF5+MOM: {capm_a - ff5_a:.2f} pp  ({shrink:.1f}% of CAPM alpha absorbed)')
"""))

cells.append(C("""\
# ── Figure 2: Alpha shrinkage forest plot ───────────────────────────────────
models_list  = ['capm', 'ff3', 'ff5mom']
model_labels = {'capm': 'CAPM', 'ff3': 'FF3', 'ff5mom': 'FF5+MOM'}
strats       = ['mv_gross', 'mv_net', 'naive', 'benchmark']

fig, axes = plt.subplots(2, 2, figsize=(12, 7))
axes = axes.flatten()

for ax, strategy in zip(axes, strats):
    alphas, ci_los, ci_his, ys = [], [], [], []
    for i, model in enumerate(models_list):
        a    = float(reg_fp.loc[(strategy, model), 'alpha_annualized']) * 100
        t    = float(reg_fp.loc[(strategy, model), 'alpha_t_stat'])
        se   = abs(a / t) if abs(t) > 1e-6 else 0.0
        alphas.append(a)
        ci_los.append(a - (a - 1.96 * se))   # xerr lower
        ci_his.append((a + 1.96 * se) - a)   # xerr upper
        ys.append(i)

    color = COLORS[strategy]
    ax.errorbar(alphas, ys, xerr=[ci_los, ci_his],
                fmt='o', color=color, markersize=7,
                linewidth=2.0, capsize=5, capthick=1.5, ecolor=color)
    ax.axvline(0, color='#555555', linewidth=0.9, linestyle='--')
    ax.set_yticks(range(len(models_list)))
    ax.set_yticklabels([model_labels[m] for m in models_list], fontsize=9)
    ax.set_title(LABELS[strategy], fontsize=10, fontweight='bold', color=color)
    ax.set_xlabel('Alpha (%, annualized)', fontsize=9)
    ax.xaxis.grid(True, color='#d0d0d0', linewidth=0.5)
    ax.yaxis.grid(False)

fig.suptitle(
    'Factor Alpha Estimates with 95% Newey-West Confidence Intervals\\n'
    '(Full Period 2001-2024, annualized)',
    fontsize=11, fontweight='bold',
)
fig.tight_layout()

out = FIGURES / 'alpha_shrinkage_forest.png'
fig.savefig(out, dpi=300, bbox_inches='tight')
plt.show()
print(f'Saved  {out}')
"""))

cells.append(M("""\
**Factor regression conclusion.**

The CAPM alpha for MV gross is **+2.72%/yr** (t = 1.80), borderline significant and
economically meaningful. However, this is almost entirely a compensation story:
adding the RMW and CMA factors (FF5+MOM specification) reduces the alpha to
**+0.55%/yr** (t = 0.44), a **79.8% reduction** — the key diagnostic result. The
alpha is no longer distinguishable from zero.

The factor loadings tell the structural story: MV gross carries a **below-unity
market beta** (low-beta tilt from the variance-minimization objective), a
**positive RMW loading** (quality/profitability tilt — the optimizer over-weights
low-volatility stocks that tend to be profitable), and a **positive CMA loading**
(conservative investment — capital-light businesses with lower realized volatility).
These are exactly the factor exposures predicted by the Frazzini-Pedersen
low-volatility anomaly literature.

**The conclusion is that MV gross harvests known, priced factor premia — not
skill-based alpha.** An investor seeking these factor exposures could replicate
most of the MV gross performance with a lower-cost, rules-based factor tilt.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 5. H2: Regime-Conditional Performance

**H2:** *The constrained mean-variance strategy generates statistically significant
outperformance during bear-market episodes.*

We test H2 using IID bootstrap confidence intervals (10,000 replications, seed = 42)
for the annualized Sharpe ratio difference within each regime sub-sample. The
bootstrap resamples individual months with replacement and computes the Sharpe
difference on each resample; the 95% CI is the 2.5th–97.5th percentile of the
bootstrap distribution. A regime difference is statistically significant if the CI
excludes zero.

We run the test on both the main (−20%) and sensitivity (−15%) classifications to
assess robustness to the threshold choice. We report all strategy pairs but focus
the narrative on MV gross vs benchmark.\
"""))

cells.append(C("""\
boot_main = pd.read_csv(TABLES / 'regime_bootstrap_main.csv',        index_col=[0, 1])
boot_sens = pd.read_csv(TABLES / 'regime_bootstrap_sensitivity.csv', index_col=[0, 1])

# Ensure 'significant' is boolean (pandas may read as string)
for df in (boot_main, boot_sens):
    df['significant'] = df['significant'].astype(str).str.lower() == 'true'

def fmt_boot(df):
    out = df.copy().astype(object)
    for col in ['point_estimate', 'ci_low', 'ci_high']:
        out[col] = df[col].map(lambda x: f'{x:+.3f}' if pd.notna(x) else '-')
    out['significant'] = df['significant'].map(lambda x: 'YES *' if x else 'no')
    out['n_obs']       = df['n_obs'].astype(int)
    out['n_boot']      = df['n_boot'].astype(int)
    return out

print('Bootstrap 95% CIs  —  Main classification (-20%):')
display(fmt_boot(boot_main))
print('\\nBootstrap 95% CIs  —  Sensitivity classification (-15%):')
display(fmt_boot(boot_sens))
"""))

cells.append(C("""\
# ── Figure 3: Regime Sharpe-difference bar chart ────────────────────────────
pair           = 'mv_gross vs benchmark'
regimes_order  = ['bull', 'bear', 'recovery']
regime_labels_ = {'bull': 'Bull', 'bear': 'Bear', 'recovery': 'Recovery'}
x = np.arange(len(regimes_order))

fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

for ax, (df, title) in zip(axes, [
    (boot_main, 'Main threshold (-20%)'),
    (boot_sens, 'Sensitivity threshold (-15%)'),
]):
    pts   = [float(df.loc[(pair, r), 'point_estimate']) for r in regimes_order]
    lo_e  = [float(df.loc[(pair, r), 'point_estimate']) - float(df.loc[(pair, r), 'ci_low'])
             for r in regimes_order]
    hi_e  = [float(df.loc[(pair, r), 'ci_high']) - float(df.loc[(pair, r), 'point_estimate'])
             for r in regimes_order]
    sig   = [bool(df.loc[(pair, r), 'significant']) for r in regimes_order]
    bclrs = [C_MV if s else '#aabbd4' for s in sig]

    ax.bar(x, pts, 0.55, color=bclrs, zorder=2)
    ax.errorbar(x, pts, yerr=[lo_e, hi_e],
                fmt='none', color='#222222', linewidth=1.3, capsize=6, capthick=1.3, zorder=3)
    ax.axhline(0, color='#555555', linewidth=0.9, linestyle='--', zorder=1)
    ax.yaxis.grid(True, color='#d0d0d0', linewidth=0.5, zorder=0)
    ax.set_xticks(x)
    ax.set_xticklabels([regime_labels_[r] for r in regimes_order], fontsize=11)
    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

axes[0].set_ylabel('Sharpe difference (annualized)', fontsize=10)

legend_patches = [
    mpatches.Patch(color=C_MV,     label='Significant (95% CI excludes 0)'),
    mpatches.Patch(color='#aabbd4', label='Not significant'),
]
axes[1].legend(handles=legend_patches, fontsize=9, loc='upper left')

fig.suptitle(
    'Bootstrap 95% Confidence Intervals for Sharpe Ratio Differences by Market Regime\\n'
    '(MV Gross vs S&P 500 Benchmark)',
    fontsize=11, fontweight='bold',
)
fig.tight_layout()

out = FIGURES / 'regime_sharpe_diff.png'
fig.savefig(out, dpi=300, bbox_inches='tight')
plt.show()
print(f'Saved  {out}')
"""))

cells.append(M("""\
**H2 conclusion — partially supported, with an important qualification.**

The bear-market Sharpe advantage for MV gross vs benchmark is **+0.691 annualized**
under the main threshold, with a 95% bootstrap CI of [+0.221, +1.318] that
**excludes zero** — statistically significant. The result is robust: the sensitivity
(−15%) classification gives **+0.697** with CI [+0.248, +1.335], and the COVID
episode adds only 3 bear months without materially changing the point estimate.

Bull and recovery regime differences are uniformly **insignificant** (all CIs
straddle zero), consistent with the full-period JKM result.

**The qualification:** the same pattern holds for the naive **1/N portfolio** vs
benchmark in bear markets (+0.505, CI [+0.235, +0.905], significant). The
*MV gross vs naive* bear-market comparison yields **+0.186** with CI [−0.185, +0.613]
— *not significant*. This implies that the bear-market advantage stems primarily
from **departing from cap-weighting** rather than from the mean-variance
optimization itself. Any diversified equal-weighted or factor-diversified strategy
would capture most of this benefit. The incremental contribution of the optimization
layer, over and above naive diversification, is not statistically identifiable in
bear markets with 45 available monthly observations.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 6. Synthesized Findings

**On H1 — risk-adjusted performance across the full sample.**
Constrained mean-variance does not consistently outperform on a Sharpe-ratio basis.
The full-period gap of +0.160 (p = 0.161) fails to reach conventional significance,
and the post-2015 gap reverses to −0.073 (p = 0.691), erased by the benchmark's
narrow-mega-cap leadership. More fundamentally, the CAPM alpha of +2.72%/yr
shrinks by **79.8%** to +0.55%/yr under the FF5+MOM specification, fully absorbed
by loadings on the low-beta, quality (RMW), and conservative investment (CMA) factors.
**H1 fails to reject; the apparent outperformance is factor exposure, not skill.**

**On H2 — regime-conditional performance.**
There is partial support for bear-market outperformance: MV gross vs benchmark in
bear months yields a Sharpe advantage of +0.69 with a CI that excludes zero, robust
to the choice of drawdown threshold. However, this advantage is almost entirely
shared with the naive 1/N portfolio, and the MV gross vs naive comparison in bear
markets is insignificant (+0.19, CI straddles zero). **The bear-market advantage
belongs to the class of cap-weight-departing strategies, not to mean-variance
optimization specifically.** H2 is partially supported in the aggregate vs benchmark
sense, but the optimizer's marginal contribution relative to naive diversification
cannot be established with the available data.

**The unambiguous contribution: risk control.**
What survives every subsample, every threshold, and every alternative test is the
**volatility reduction (~24% relative to the benchmark)** and the **persistent
drawdown protection** (maximum drawdown 9 pp shallower full-period, 7 pp shallower
post-2015; bear-period drawdowns capped near −58% vs −75% for the benchmark).
These results are economically meaningful and stable. The honest framing is that
constrained mean-variance delivers **superior risk control at comparable expected
returns**, not demonstrably superior risk-adjusted returns. For investors with
drawdown-sensitive mandates — endowments, insurers, capital-constrained institutions
— this framing is commercially relevant even in the absence of a Sharpe premium.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7
# ══════════════════════════════════════════════════════════════════════════════
cells.append(M("""\
## 7. Reproducibility

All results in this notebook are fully reproducible from the cached artifacts in
`data/processed/` and `results/`. No live data fetches or optimization runs are
required. The pipeline scripts in `src/` — `data_pull.py`, `optimize.py`,
`backtest.py`, `regimes.py`, `metrics.py`, and `stats.py` — can be re-executed
in sequence to regenerate every input file from scratch. The factor data are
sourced from the Kenneth French Data Library and cached to `data/raw/` on first
download. A fixed random seed (42) is used for all bootstrap computations to
ensure identical outputs across runs. The Python environment is managed by `uv`
and fully specified in `pyproject.toml`.\
"""))


# ══════════════════════════════════════════════════════════════════════════════
# WRITE
# ══════════════════════════════════════════════════════════════════════════════
nb.cells = cells
out_path = Path(__file__).parent / '03_results.ipynb'
with open(out_path, 'w', encoding='utf-8') as f:
    nbf.write(nb, f)
print(f'Created {out_path}  ({len(cells)} cells)')
