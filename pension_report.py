"""
Pension Validation Report — PDF Generator
Produces a multi-page PDF with charts and analysis tables.
"""

import math
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import BalancedColumns

# ─────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────
NAVY   = "#1B2A4A"
TEAL   = "#0B7A75"
GOLD   = "#D4A017"
SLATE  = "#4A5568"
RED    = "#C0392B"
GREEN  = "#27AE60"
LGREY  = "#F5F6FA"
WHITE  = "#FFFFFF"

C_NAVY  = colors.HexColor(NAVY)
C_TEAL  = colors.HexColor(TEAL)
C_GOLD  = colors.HexColor(GOLD)
C_SLATE = colors.HexColor(SLATE)
C_RED   = colors.HexColor(RED)
C_GREEN = colors.HexColor(GREEN)
C_LGREY = colors.HexColor(LGREY)

# ─────────────────────────────────────────────
# FINANCIAL CALCULATIONS
# ─────────────────────────────────────────────

def fv_pot(pv, annual_rate, months, monthly_contrib):
    r = (1 + annual_rate) ** (1 / 12) - 1
    fv_pv = pv * (1 + r) ** months
    fv_c  = monthly_contrib * ((1 + r) ** months - 1) / r if r > 0 else monthly_contrib * months
    return fv_pv + fv_c

def years_to_depletion(pot, annual_withdrawal, growth_rate):
    if growth_rate == 0:
        return pot / annual_withdrawal
    ratio = pot * growth_rate / annual_withdrawal
    if ratio >= 1:
        return float("inf")
    return -math.log(1 - ratio) / math.log(1 + growth_rate)

def uk_income_tax(gross, pa=12_570, brl=50_270):
    if gross <= pa:
        return 0.0
    taxable = gross - pa
    if gross <= brl:
        return taxable * 0.20
    return (brl - pa) * 0.20 + (gross - brl) * 0.40

# ── His DC pot projection ──────────────────────────────────────
r10 = 0.10  # 10% annual growth (Aegon)
combined_pv = 172_000  # Aon £135k + Aegon £37k

months = list(range(0, 50))
pot_values = []
v = combined_pv
monthly_r = (1 + r10) ** (1 / 12) - 1
for m in months:
    pot_values.append(v)
    contrib = (1_462 + 165) if m < 3 else (2_800 + 165)
    v = v * (1 + monthly_r) + contrib

his_dc_at_retirement = pot_values[49]   # ~£425k at 49 months
his_dc_dec2029 = pot_values[42]         # ~£382k at 42 months (Dec 2029)

# ── Wife DC pot projection ─────────────────────────────────────
r9 = 0.09
wife_pv = 34_500
monthly_r9 = (1 + r9) ** (1 / 12) - 1
wife_values = []
v = wife_pv
for m in range(49):
    wife_values.append(v)
    contrib = (216 + 100) if m < 1 else (816 + 100)
    v = v * (1 + monthly_r9) + contrib
wife_at_retirement = wife_values[-1]

# ── PCLS & drawdown pots ───────────────────────────────────────
his_pcls_proj   = his_dc_at_retirement * 0.25
his_drawdown    = his_dc_at_retirement * 0.75
wife_pcls       = wife_at_retirement   * 0.25
wife_drawdown   = wife_at_retirement   * 0.75

# ── Income timeline ────────────────────────────────────────────
db1_at55 = 16_300
db1_at58 = db1_at55 * 1.03 ** 3
years_rel = list(range(0, 31))       # 0 = retirement 2030
target    = [50_000 * 1.03 ** y for y in years_rel]

def guaranteed_income(year_rel):
    """Guaranteed income relative to retirement year (year 0 = 2030, him 58)."""
    db1 = db1_at58 * 1.03 ** year_rel
    db23 = (1_800 + 1_800) * 1.03 ** max(0, year_rel - 2) if year_rel >= 2 else 0
    wife_db = 4_000 * 1.03 ** max(0, year_rel - 3) if year_rel >= 3 else 0
    sp_him  = 11_500 * 1.03 ** max(0, year_rel - 9) if year_rel >= 9 else 0
    sp_wife = 11_500 * 1.03 ** max(0, year_rel - 10) if year_rel >= 10 else 0
    return db1 + db23 + wife_db + sp_him + sp_wife

guaranteed = [guaranteed_income(y) for y in years_rel]
dc_needed  = [max(0, t - g) for t, g in zip(target, guaranteed)]

# ── Drawdown duration (various rates, nominal 8% growth) ──────
GROWTH  = 0.08
GROWTH_REAL = (1.08 / 1.03) - 1  # ~4.85%
rates   = [0.06, 0.07, 0.08, 0.09]
labels  = ["6%", "7%", "8%", "9%"]

# Pot depletion curves for each rate (using £315k user estimate → drawdown £236,250)
drawdown_315 = 236_250
drawdown_425 = his_drawdown

def depletion_curve(drawdown_pot, withdrawal_annual, growth, years=35):
    curve = [drawdown_pot]
    v = drawdown_pot
    for _ in range(years):
        v = v * (1 + growth) - withdrawal_annual
        curve.append(max(v, 0))
        if v <= 0:
            curve += [0] * (years - len(curve) + 1)
            break
    return curve[:years + 1]

# ─────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────

def fig_to_image(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf

def styled_fig(w=10, h=5):
    fig = plt.figure(figsize=(w, h), facecolor=WHITE)
    return fig

# ─────────────────────────────────────────────
# CHART 1 — DC Pot Accumulation
# ─────────────────────────────────────────────

def chart_accumulation():
    fig = styled_fig(10, 4.5)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)
    fig.patch.set_facecolor(WHITE)

    x_months = list(range(49))
    x_years  = [2026 + m / 12 for m in x_months]

    ax.fill_between(x_years, [v / 1000 for v in pot_values[:49]],
                    alpha=0.15, color=TEAL)
    ax.plot(x_years, [v / 1000 for v in pot_values[:49]],
            color=TEAL, lw=2.5, label="His DC (Aon+Aegon combined)")

    wife_x = [2026 + m / 12 for m in range(49)]
    ax.fill_between(wife_x, [v / 1000 for v in wife_values],
                    alpha=0.12, color=GOLD)
    ax.plot(wife_x, [v / 1000 for v in wife_values],
            color=GOLD, lw=2.5, label="Wife's DC")

    # Annotation lines
    ax.axvline(2029 + 7 / 12, color=SLATE, lw=1, ls="--", alpha=0.6)
    ax.text(2029.65, 5, "Your\n£315k\nestimate", fontsize=7.5, color=SLATE,
            va="bottom")
    ax.axvline(2030.5, color=NAVY, lw=1.5, ls="--", alpha=0.7)
    ax.text(2030.55, 5, "Retirement", fontsize=8, color=NAVY, va="bottom",
            fontweight="bold")

    # Key value labels
    ax.annotate(f"£{his_dc_at_retirement/1000:.0f}k",
                xy=(2030.5, his_dc_at_retirement / 1000),
                xytext=(2028.8, his_dc_at_retirement / 1000 + 20),
                arrowprops=dict(arrowstyle="->", color=TEAL, lw=1.2),
                fontsize=9, color=TEAL, fontweight="bold")
    ax.annotate(f"£{wife_at_retirement/1000:.0f}k",
                xy=(2030.5, wife_at_retirement / 1000),
                xytext=(2029.0, wife_at_retirement / 1000 + 30),
                arrowprops=dict(arrowstyle="->", color=GOLD, lw=1.2),
                fontsize=9, color=GOLD, fontweight="bold")
    ax.annotate(f"£315k\n(your estimate)",
                xy=(2029.6, 315),
                xytext=(2027.5, 320),
                arrowprops=dict(arrowstyle="->", color=SLATE, lw=1),
                fontsize=8, color=SLATE)

    ax.set_xlabel("Year", color=SLATE, fontsize=9)
    ax.set_ylabel("Pot Value (£000s)", color=SLATE, fontsize=9)
    ax.set_title("DC Pot Accumulation to Retirement", fontsize=12,
                 color=NAVY, fontweight="bold", pad=12)
    ax.legend(fontsize=9, framealpha=0.9)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.set_xlim(2026, 2031.5)
    ax.set_ylim(0, max(pot_values[:49]) / 1000 * 1.15)
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 2 — Income Gap Analysis
# ─────────────────────────────────────────────

def chart_income_gap():
    fig = styled_fig(10, 5)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    years_abs = [2030 + y for y in years_rel]

    ax.stackplot(years_abs,
                 [[min(g, t) for g, t in zip(guaranteed, target)],
                  [max(0, t - g) for t, g in zip(target, guaranteed)]],
                 colors=[TEAL, "#E8F4F8"],
                 labels=["Guaranteed income (DB + State pensions)", "DC drawdown needed"],
                 alpha=0.85)
    ax.plot(years_abs, target, color=NAVY, lw=2, ls="--", label="£50k target (3% inflation)")

    # Key event markers
    events = {
        2030: ("Retirement\n(DB1 only)", 0),
        2032: ("DB2 & DB3\nstart", 0),
        2033: ("Wife's\nDB1", 0),
        2039: ("His state\npension", 0),
        2040: ("Wife's state\npension", 0),
    }
    for yr, (lbl, _) in events.items():
        ax.axvline(yr, color=GOLD, lw=0.8, ls=":", alpha=0.7)
        ax.text(yr + 0.1, max(target) * 0.95, lbl, fontsize=6.5,
                color=GOLD, rotation=90, va="top")

    ax.set_xlabel("Year", color=SLATE, fontsize=9)
    ax.set_ylabel("Annual Income (£)", color=SLATE, fontsize=9)
    ax.set_title("Retirement Income Gap Analysis (Gross)", fontsize=12,
                 color=NAVY, fontweight="bold", pad=12)
    ax.legend(fontsize=8.5, loc="upper left", framealpha=0.92)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax.set_xlim(2030, 2060)
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 3 — Drawdown Duration (£315k scenario)
# ─────────────────────────────────────────────

def chart_drawdown():
    fig = styled_fig(10, 5)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    palette = [GREEN, TEAL, GOLD, RED]
    curve_years = list(range(36))

    for rate, label, col in zip(rates, labels, palette):
        annual_w = 315_000 * rate
        curve = depletion_curve(drawdown_315, annual_w, GROWTH, 35)
        ax.plot(curve_years, [v / 1000 for v in curve],
                color=col, lw=2.2, label=f"{label} withdrawal (£{annual_w:,.0f}/yr)")

    # Life expectancy band
    ax.axvspan(25, 30, alpha=0.07, color=NAVY, label="Typical life exp. range (83–88)")
    ax.axhline(0, color="#999999", lw=0.8)

    # Age labels on x-axis
    ages = [58 + y for y in curve_years]
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(range(0, 36, 5))
    ax2.set_xticklabels([str(58 + i) for i in range(0, 36, 5)], fontsize=8, color=SLATE)
    ax2.set_xlabel("Age (his)", fontsize=8.5, color=SLATE)
    ax2.spines[["top", "right"]].set_visible(False)

    ax.set_xlabel("Years into retirement", color=SLATE, fontsize=9)
    ax.set_ylabel("Remaining Pot (£000s)", color=SLATE, fontsize=9)
    ax.set_title("DC Pot Longevity by Withdrawal Rate\n(Starting pot £315k → £236k after 25% PCLS, 8% growth)",
                 fontsize=11, color=NAVY, fontweight="bold", pad=12)
    ax.legend(fontsize=8.5, loc="upper right", framealpha=0.92)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"£{x:.0f}k"))
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 4 — Drawdown Duration (projected £425k)
# ─────────────────────────────────────────────

def chart_drawdown_425():
    fig = styled_fig(10, 5)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    palette = [GREEN, TEAL, GOLD, RED]
    curve_years = list(range(36))

    for rate, label, col in zip(rates, labels, palette):
        annual_w = 425_000 * rate
        curve = depletion_curve(drawdown_425, annual_w, GROWTH, 35)
        ax.plot(curve_years, [v / 1000 for v in curve],
                color=col, lw=2.2, label=f"{label} withdrawal (£{annual_w:,.0f}/yr)")

    ax.axvspan(25, 30, alpha=0.07, color=NAVY, label="Typical life exp. range (83–88)")
    ax.axhline(0, color="#999999", lw=0.8)

    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(range(0, 36, 5))
    ax2.set_xticklabels([str(58 + i) for i in range(0, 36, 5)], fontsize=8, color=SLATE)
    ax2.set_xlabel("Age (his)", fontsize=8.5, color=SLATE)
    ax2.spines[["top", "right"]].set_visible(False)

    ax.set_xlabel("Years into retirement", color=SLATE, fontsize=9)
    ax.set_ylabel("Remaining Pot (£000s)", color=SLATE, fontsize=9)
    ax.set_title("DC Pot Longevity by Withdrawal Rate\n(Projected pot £425k → £319k after 25% PCLS, 8% growth)",
                 fontsize=11, color=NAVY, fontweight="bold", pad=12)
    ax.legend(fontsize=8.5, loc="upper right", framealpha=0.92)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"£{x:.0f}k"))
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 5 — Tax Comparison (income split)
# ─────────────────────────────────────────────

def chart_tax():
    fig = styled_fig(8, 4)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    strategies = ["All to\nhim", "Split\n£25k/£25k", "DB+top-up\nvs min-wife"]
    net_values  = [42_514, 45_028, 44_952]
    tax_values  = [7_486,  4_972,  5_048]
    colours_net = [NAVY, TEAL, TEAL]
    colours_tax = [RED, GOLD, GOLD]

    x = np.arange(len(strategies))
    w = 0.35

    b1 = ax.bar(x - w / 2, net_values, w, color=colours_net, alpha=0.85, label="Net income")
    b2 = ax.bar(x + w / 2, tax_values,  w, color=colours_tax, alpha=0.85, label="Tax paid")

    for bar in b1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                f"£{bar.get_height():,.0f}", ha="center", va="bottom",
                fontsize=8, color=NAVY, fontweight="bold")
    for bar in b2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                f"£{bar.get_height():,.0f}", ha="center", va="bottom",
                fontsize=8, color=RED)

    ax.annotate("Best option\n+£2,514/yr", xy=(1 - w / 2, 45_028),
                xytext=(1.6, 43_000),
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5),
                fontsize=8.5, color=GREEN, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(strategies, fontsize=9, color=SLATE)
    ax.set_ylabel("Annual Amount (£)", color=SLATE, fontsize=9)
    ax.set_title("Income Tax Comparison — £50,000 Gross Target", fontsize=11,
                 color=NAVY, fontweight="bold", pad=10)
    ax.legend(fontsize=9, framealpha=0.9)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax.set_ylim(0, 55_000)
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 6 — Guaranteed income waterfall
# ─────────────────────────────────────────────

def chart_income_waterfall():
    fig = styled_fig(9, 4.5)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    labels_wf = ["His DB1\n(at 55→58)", "His DB2\n& DB3\n(at 60)", "Wife's\nDB1\n(at 60)",
                 "His State\nPension\n(at 67)", "Wife's\nState\nPension\n(at 67)", "Total\nguaranteed"]
    values_wf  = [db1_at58, 3_600, 4_000, 11_500, 11_500,
                  db1_at58 + 3_600 + 4_000 + 11_500 + 11_500]
    cumulative = [0,
                  db1_at58,
                  db1_at58 + 3_600,
                  db1_at58 + 3_600 + 4_000,
                  db1_at58 + 3_600 + 4_000 + 11_500,
                  0]  # total bar starts at 0

    bar_colors = [TEAL, TEAL, TEAL, NAVY, NAVY, GREEN]
    x = np.arange(len(labels_wf))

    for i, (lbl, val, bot, col) in enumerate(zip(labels_wf, values_wf, cumulative, bar_colors)):
        if i < 5:
            ax.bar(x[i], val, bottom=bot, color=col, alpha=0.85, width=0.55)
            ax.text(x[i], bot + val / 2, f"£{val:,.0f}", ha="center", va="center",
                    fontsize=8, color=WHITE, fontweight="bold")
        else:
            ax.bar(x[i], val, bottom=0, color=col, alpha=0.85, width=0.55)
            ax.text(x[i], val / 2, f"£{val:,.0f}", ha="center", va="center",
                    fontsize=9, color=WHITE, fontweight="bold")

    ax.axhline(50_000, color=RED, lw=1.5, ls="--", alpha=0.8, label="£50k target")
    ax.text(5.45, 51_000, "£50,000\ntarget", fontsize=8, color=RED, va="bottom")

    ax.set_xticks(x)
    ax.set_xticklabels(labels_wf, fontsize=8.5, color=SLATE)
    ax.set_ylabel("Annual Income (£)", color=SLATE, fontsize=9)
    ax.set_title("Guaranteed Income Waterfall (at today's values)", fontsize=11,
                 color=NAVY, fontweight="bold", pad=10)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"£{v:,.0f}"))
    ax.legend(fontsize=9, framealpha=0.9)
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# CHART 7 — Withdrawal rate duration bar chart
# ─────────────────────────────────────────────

def chart_duration_bars():
    fig = styled_fig(8, 4)
    ax = fig.add_subplot(111)
    ax.set_facecolor(LGREY)

    rate_labels = ["6%", "7%", "8%", "9%"]
    nom_years_315 = []
    nom_years_425 = []
    for r in rates:
        w315 = years_to_depletion(drawdown_315, 315_000 * r, GROWTH)
        w425 = years_to_depletion(drawdown_425, 425_000 * r, GROWTH)
        nom_years_315.append(35 if w315 == float("inf") else w315)
        nom_years_425.append(35 if w425 == float("inf") else w425)

    x = np.arange(len(rate_labels))
    w = 0.35
    bars1 = ax.bar(x - w / 2, nom_years_315, w, color=TEAL, alpha=0.85,
                   label="£315k pot (your estimate)")
    bars2 = ax.bar(x + w / 2, nom_years_425, w, color=NAVY, alpha=0.85,
                   label="£425k pot (model projection)")

    for b, v, r in zip(bars1, nom_years_315, rates):
        lbl = "Indefinite" if years_to_depletion(drawdown_315, 315_000 * r, GROWTH) == float("inf") else f"{v:.0f} yrs"
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3, lbl,
                ha="center", va="bottom", fontsize=8, color=TEAL, fontweight="bold")
    for b, v, r in zip(bars2, nom_years_425, rates):
        lbl = "Indefinite" if years_to_depletion(drawdown_425, 425_000 * r, GROWTH) == float("inf") else f"{v:.0f} yrs"
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3, lbl,
                ha="center", va="bottom", fontsize=8, color=NAVY, fontweight="bold")

    # Life expectancy band
    ax.axhspan(25, 30, alpha=0.10, color=GOLD, label="Life expectancy range (25–30 yrs)")

    ax.set_xticks(x)
    ax.set_xticklabels([f"{l} withdrawal" for l in rate_labels], fontsize=9, color=SLATE)
    ax.set_ylabel("Years until pot depletes", color=SLATE, fontsize=9)
    ax.set_title("Pot Longevity by Withdrawal Rate (8% nominal growth)", fontsize=11,
                 color=NAVY, fontweight="bold", pad=10)
    ax.legend(fontsize=9, framealpha=0.9)
    ax.tick_params(colors=SLATE, labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CCCCCC")
    ax.yaxis.grid(True, color="#DDDDDD", lw=0.7)
    ax.set_ylim(0, 38)
    fig.tight_layout()
    return fig_to_image(fig)

# ─────────────────────────────────────────────
# PDF STYLES
# ─────────────────────────────────────────────

def build_styles():
    base = getSampleStyleSheet()
    s = {}

    s["h1"] = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=22,
                              textColor=C_NAVY, spaceAfter=8, leading=26)
    s["h2"] = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14,
                              textColor=C_TEAL, spaceAfter=6, spaceBefore=14, leading=18)
    s["h3"] = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11,
                              textColor=C_NAVY, spaceAfter=4, spaceBefore=8, leading=14)
    s["body"] = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               textColor=C_SLATE, spaceAfter=5, leading=14,
                               alignment=TA_JUSTIFY)
    s["body_bold"] = ParagraphStyle("body_bold", fontName="Helvetica-Bold", fontSize=9.5,
                                    textColor=C_NAVY, spaceAfter=4, leading=14)
    s["flag"] = ParagraphStyle("flag", fontName="Helvetica", fontSize=9,
                               textColor=colors.HexColor("#7B341E"),
                               backColor=colors.HexColor("#FFF5F0"),
                               spaceAfter=5, spaceBefore=4, leading=14,
                               leftIndent=8, rightIndent=8,
                               borderPad=4)
    s["ok"] = ParagraphStyle("ok", fontName="Helvetica", fontSize=9,
                              textColor=colors.HexColor("#1A4731"),
                              backColor=colors.HexColor("#F0FFF4"),
                              spaceAfter=5, spaceBefore=4, leading=14,
                              leftIndent=8, rightIndent=8, borderPad=4)
    s["caption"] = ParagraphStyle("caption", fontName="Helvetica-Oblique", fontSize=8,
                                  textColor=C_SLATE, spaceAfter=8, alignment=TA_CENTER)
    s["disclaimer"] = ParagraphStyle("disclaimer", fontName="Helvetica", fontSize=7.5,
                                     textColor=C_SLATE, spaceAfter=4, leading=11,
                                     alignment=TA_JUSTIFY)
    s["subtitle"] = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11,
                                   textColor=C_SLATE, spaceAfter=4, leading=14)
    s["toc"] = ParagraphStyle("toc", fontName="Helvetica", fontSize=10,
                              textColor=C_NAVY, spaceAfter=3, leading=14,
                              leftIndent=12)
    return s

def tbl_style_default():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, -1), C_LGREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_LGREY]),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 8.5),
        ("ALIGN",      (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN",      (0, 1), (0, -1), "LEFT"),
        ("TEXTCOLOR",  (0, 1), (-1, -1), C_SLATE),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ])

def img(buf, width_cm):
    w = width_cm * cm
    im = Image(buf, width=w, height=w * 0.48)
    im.hAlign = "CENTER"
    return im

# ─────────────────────────────────────────────
# BUILD THE PDF
# ─────────────────────────────────────────────

def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title="Pension Validation Report",
        author="Finance Skills Analysis",
    )
    W = A4[0] - 36 * mm   # usable width
    s = build_styles()
    story = []

    # ── COVER ──────────────────────────────────────────────────
    story.append(Spacer(1, 30 * mm))
    story.append(HRFlowable(width="100%", thickness=3, color=C_TEAL, spaceAfter=8))
    story.append(Paragraph("Pension Validation Report", s["h1"]))
    story.append(Paragraph("Prepared May 2026  ·  Confidential", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=C_GOLD, spaceAfter=20))

    cover_data = [
        ["Prepared for", "You & Your Wife"],
        ["Current ages", "54 (him) · 53 (wife)"],
        ["Planned retirement", "58 (him) · 57 (wife) — mid 2030"],
        ["Income target", "£50,000/year gross"],
        ["Analysis date", "May 2026"],
        ["Skills applied", "time-value-of-money · tax-efficiency · savings-goals\ninvestment-policy · liquidity-management"],
    ]
    ct = Table([[k, v] for k, v in cover_data], colWidths=[60 * mm, W - 60 * mm])
    ct.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",  (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",  (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), C_NAVY),
        ("TEXTCOLOR", (1, 0), (1, -1), C_SLATE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, C_LGREY]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ct)
    story.append(Spacer(1, 10 * mm))

    # Summary scorecard
    story.append(Paragraph("Executive Summary", s["h2"]))
    score_data = [
        ["Area", "Status", "Finding"],
        ["DC accumulation", "✓  On track", "Projected £425k, not £315k — Aon pot may be missing from your estimate"],
        ["Retirement income", "✓  Achievable", "DB1 + DC drawdown covers £50k from day one"],
        ["Long-term sustainability", "✓  Good", "DB + state pensions absorb the load by age 67–68"],
        ["Withdrawal rate", "⚠  Use ≤7%", "8–9% risks depleting the pot before age 73–77"],
        ["Tax efficiency", "⚠  Improve", "Splitting income saves ~£2,500/year"],
        ["Investment risk", "⚠  Review", "High-equity allocation 4 years from retirement"],
        ["DB pension timing", "⚠  Decide", "DB1 available next year at 55 — take vs defer decision needed"],
        ["Aon transfer", "⚠  Check", "Verify no safeguarded benefits before transferring"],
    ]
    st = Table(score_data, colWidths=[45 * mm, 38 * mm, W - 83 * mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_LGREY]),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR",  (0, 1), (0, -1), C_SLATE),
        ("TEXTCOLOR",  (2, 1), (2, -1), C_SLATE),
        # Colour status column
        ("TEXTCOLOR",  (1, 1), (1, 3), colors.HexColor(GREEN)),
        ("TEXTCOLOR",  (1, 4), (1, -1), colors.HexColor(GOLD)),
        ("FONTNAME",   (1, 1), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (1, 1), (1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(st)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "<i>This report is for educational planning purposes only. Figures are projections, "
        "not guarantees. Consult an FCA-authorised financial adviser before acting on this analysis.</i>",
        s["disclaimer"]))

    story.append(PageBreak())

    # ── SECTION 1 — ASSET SUMMARY ──────────────────────────────
    story.append(Paragraph("1.  Asset Summary", s["h2"]))
    story.append(Paragraph(
        "Your pension wealth comprises DC (defined contribution) pots, DB (defined benefit) "
        "pensions, and future state pension entitlements. The table below summarises all assets.",
        s["body"]))

    asset_data = [
        ["Asset", "Owner", "Type", "Current Value", "At / From"],
        ["Aon DC pot", "Him", "DC", "£135,000", "Transfers to Aegon"],
        ["Aegon DC pot", "Him", "DC", "£37,000", "Retirement (58)"],
        ["Personal DC pot", "Wife", "DC", "£34,500", "Retirement (57)"],
        ["DB Pension 1", "Him", "DB", "£16,300/yr", "Age 55 (next year!)"],
        ["DB Pension 2", "Him", "DB", "£1,800/yr", "Age 60 (2032)"],
        ["DB Pension 3", "Him", "DB", "£1,800/yr", "Age 60 (2032)"],
        ["DB Pension 1", "Wife", "DB", "£4,000/yr", "Age 60 (2033)"],
        ["State Pension", "Him", "SP", "~£11,500/yr", "Age 67 (2039)"],
        ["State Pension", "Wife", "SP", "~£11,500/yr", "Age 67 (2040)"],
    ]
    at = Table(asset_data, colWidths=[50*mm, 22*mm, 18*mm, 38*mm, W - 128*mm])
    at.setStyle(tbl_style_default())
    story.append(at)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "All DB pensions increase at 3% CPI per year once in payment. All DB pensions carry a "
        "50% spouse's pension on death. You have confirmed you will NOT take the DB commuted lump sum.",
        s["body"]))

    story.append(PageBreak())

    # ── SECTION 2 — DC POT PROJECTIONS ─────────────────────────
    story.append(Paragraph("2.  DC Pot Projections to Retirement", s["h2"]))
    story.append(Paragraph(
        "Projections use the growth rates you supplied (10% for Aegon, 9% for your wife's DC) "
        "and assume the Aon pot (£135,000) transfers to Aegon promptly. Contributions follow the "
        "schedule you provided.",
        s["body"]))

    story.append(img(chart_accumulation(), 16.5))
    story.append(Paragraph(
        "Chart 1 — DC pot growth from today to retirement. The dashed line marks your stated "
        "£315,000 estimate at end-2029; model projects £382k at that date and £425k at mid-2030.",
        s["caption"]))

    proj_data = [
        ["Date", "Milestone", "His DC (combined)", "Wife's DC"],
        ["May 2026", "Today", "£172,000", "£34,500"],
        ["Jul 2026", "Phase 1 contributions end", "£181,000", "£35,100"],
        ["Dec 2029", "Your '2029' estimate", "£382,000 (model)", "£93,000"],
        ["Mid 2030", "His retirement (age 58)", "£425,000", "—"],
        ["Mid 2030", "Wife's retirement (age 57)", "—", "£102,000"],
    ]
    pt = Table(proj_data, colWidths=[28*mm, 60*mm, 45*mm, W - 133*mm])
    pt.setStyle(tbl_style_default())
    story.append(pt)

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "⚠  Flag: Your estimate of £315,000 is approximately £67,000 below the model projection. "
        "The most likely cause is that the Aon pot (£135,000) has not been included in your own "
        "spreadsheet. Once transferred, the combined Aegon pot is substantially larger. "
        "Verify this with your Aegon adviser before relying on £315,000 as the planning figure.",
        s["flag"]))

    story.append(PageBreak())

    # ── SECTION 3 — TAX-FREE CASH ───────────────────────────────
    story.append(Paragraph("3.  Tax-Free Cash (PCLS)", s["h2"]))
    story.append(Paragraph(
        "You have elected to take the 25% Pension Commencement Lump Sum (PCLS) from each DC pot "
        "while NOT taking the DB commuted lump sums. The table below shows the amounts.",
        s["body"]))

    pcls_data = [
        ["Pot", "Total Pot Value", "PCLS (25%)", "Remaining Drawdown Pot"],
        ["His DC (your £315k estimate)", "£315,000", "£78,750", "£236,250"],
        ["His DC (model projection)", "£425,000", "£106,250", "£318,750"],
        ["Wife's DC", "£102,000", "£25,500", "£76,500"],
        ["TOTAL (using model)", "£527,000", "£131,750", "£395,250"],
    ]
    pct = Table(pcls_data, colWidths=[60*mm, 38*mm, 32*mm, W - 130*mm])
    pct.setStyle(tbl_style_default())
    # Highlight total row
    pct.setStyle(TableStyle([
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F4F8")),
        ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",  (0, -1), (-1, -1), C_NAVY),
    ]))
    story.append(pct)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Alternative: Monthly Tax-Free Income via UFPLS", s["h3"]))
    story.append(Paragraph(
        "Instead of taking the PCLS as a single lump sum, you could use Uncrystallised Fund "
        "Pension Lump Sums (UFPLS). Each monthly withdrawal is 25% tax-free and 75% taxable — "
        "the total tax-free amount over the full drawdown period is identical either way. "
        "UFPLS is useful if you want to retain IHT flexibility (uncrystallised pensions remain "
        "outside your estate for longer).",
        s["body"]))

    ufpls_data = [
        ["Monthly DC Withdrawal", "Tax-Free Element (25%)", "Taxable Element (75%)"],
        ["£1,000", "£250", "£750"],
        ["£1,500", "£375", "£1,125"],
        ["£2,000", "£500", "£1,500"],
        ["£2,500", "£625", "£1,875"],
        ["£3,000", "£750", "£2,250"],
    ]
    ut = Table(ufpls_data, colWidths=[60*mm, 55*mm, W - 115*mm])
    ut.setStyle(tbl_style_default())
    story.append(ut)

    story.append(PageBreak())

    # ── SECTION 4 — DRAWDOWN DURATION ───────────────────────────
    story.append(Paragraph("4.  Drawdown Duration Analysis", s["h2"]))
    story.append(Paragraph(
        "The charts below show how long your DC drawdown pot lasts at different withdrawal rates. "
        "The growth assumption of 8% per annum net of charges is based on your stated fund "
        "allocation: 30% L&G Global Technology Index (assumed 11% long-term) and 70% Vanguard "
        "LifeStrategy 80% Equity (assumed 7.5%), blending to approximately 8.5% gross, "
        "reduced to 8% after charges.",
        s["body"]))

    dur_data = [
        ["Rate", "Annual Withdrawal\n(on £315k)", "Monthly", "Pot lasts\n(fixed cash, 8% growth)",
         "Pot lasts\n(inflation-adj, 5% real)"],
        ["6%", "£18,900", "£1,575", "Indefinite ♻", "~20 years"],
        ["7%", "£22,050", "£1,838", "~25 years", "~15 years"],
        ["8%", "£25,200", "£2,100", "~18 years", "~13 years"],
        ["9%", "£28,350", "£2,362", "~14 years", "~11 years"],
    ]
    dt = Table(dur_data, colWidths=[18*mm, 42*mm, 25*mm, 48*mm, W - 133*mm])
    dt.setStyle(tbl_style_default())
    # Colour code rows
    dt.setStyle(TableStyle([
        ("TEXTCOLOR", (3, 1), (3, 1), colors.HexColor(GREEN)),
        ("FONTNAME",  (3, 1), (3, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (3, 2), (3, 2), colors.HexColor(TEAL)),
        ("FONTNAME",  (3, 2), (3, 2), "Helvetica-Bold"),
        ("TEXTCOLOR", (3, 3), (-1, 3), colors.HexColor(GOLD)),
        ("TEXTCOLOR", (3, 4), (-1, 4), colors.HexColor(RED)),
        ("FONTNAME",  (3, 3), (-1, 4), "Helvetica-Bold"),
    ]))
    story.append(dt)
    story.append(Spacer(1, 3 * mm))

    story.append(img(chart_drawdown(), 16.5))
    story.append(Paragraph(
        "Chart 2 — Drawdown pot longevity using your £315k estimate (£236k after 25% PCLS, 8% growth). "
        "The shaded band shows typical life expectancy range. A 6% withdrawal rate sustains the pot indefinitely.",
        s["caption"]))

    story.append(img(chart_drawdown_425(), 16.5))
    story.append(Paragraph(
        "Chart 3 — Drawdown pot longevity using the model-projected £425k (£319k after 25% PCLS). "
        "The larger pot delivers materially more income at every rate.",
        s["caption"]))

    story.append(Spacer(1, 3 * mm))
    story.append(img(chart_duration_bars(), 14))
    story.append(Paragraph(
        "Chart 4 — Years until pot depletes by withdrawal rate (nominal 8% growth). "
        "Gold band = typical life expectancy range. Only 6–7% rates are sustainable for a 25–30 year retirement.",
        s["caption"]))

    story.append(Paragraph(
        "✓  Key insight: At 6% withdrawal on the £315k pot, the annual draw (£18,900) is almost "
        "exactly matched by portfolio growth (8% of £236k = £18,880) — making the pot effectively "
        "indefinite. However, once inflation-adjusted, real purchasing power erodes faster. "
        "The good news: your DB pensions are already inflation-linked, so you may not need to "
        "increase DC withdrawals by inflation every year, significantly extending pot longevity.",
        s["ok"]))

    story.append(PageBreak())

    # ── SECTION 5 — INCOME GAP ───────────────────────────────────
    story.append(Paragraph("5.  Year-by-Year Income Analysis", s["h2"]))
    story.append(Paragraph(
        "Your £50,000 income target must be funded from a combination of DB pensions, DC drawdown, "
        "and eventually state pensions. The income gap varies significantly by year as each "
        "guaranteed source comes online.",
        s["body"]))

    story.append(img(chart_income_waterfall(), 15))
    story.append(Paragraph(
        "Chart 5 — Guaranteed income sources building up to cover the £50,000 target (today's values). "
        "Teal bars = DB pensions. Navy bars = state pensions. Green = combined total.",
        s["caption"]))

    story.append(img(chart_income_gap(), 16.5))
    story.append(Paragraph(
        "Chart 6 — Income gap over 30 years. Teal = guaranteed income. Light blue = DC drawdown needed. "
        "Dashed line = inflation-adjusted £50k target. Gap narrows sharply at age 60 and again at 67.",
        s["caption"]))

    gap_data = [
        ["Year", "His Age", "Guaranteed Income", "Gap to £50k", "Key event"],
        ["2030", "58", "£17,811", "£32,189", "Retirement — DB1 only in payment"],
        ["2031", "59", "£18,345", "£31,655", ""],
        ["2032", "60", "£22,496", "£27,504", "His DB2 & DB3 start (£3,600/yr combined)"],
        ["2033", "61", "£27,171", "£22,829", "Wife's DB1 starts (£4,000/yr)"],
        ["2039", "67", "£43,944", "~£21k*", "His state pension starts"],
        ["2040", "68", "£56,417", "~£11k*", "Wife's state pension — guaranteed nearly covers target"],
    ]
    gt = Table(gap_data, colWidths=[18*mm, 18*mm, 42*mm, 30*mm, W - 108*mm])
    gt.setStyle(tbl_style_default())
    story.append(gt)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "* Gap shown vs inflation-adjusted target (3%/yr). Your DB pensions are CPI-linked so they "
        "track the target. By age 68, guaranteed income fully covers the income target.",
        s["body"]))

    story.append(PageBreak())

    # ── SECTION 6 — TAX ─────────────────────────────────────────
    story.append(Paragraph("6.  Income Tax Optimisation", s["h2"]))
    story.append(Paragraph(
        "Both of you have personal allowances (£12,570 each, 2024/25). Splitting income "
        "across both spouses materially reduces the tax bill on £50,000 gross joint income.",
        s["body"]))

    story.append(img(chart_tax(), 13))
    story.append(Paragraph(
        "Chart 7 — Net income after tax across three income-splitting strategies on £50,000 gross. "
        "Equal split saves £2,514/year versus drawing all income through one person.",
        s["caption"]))

    tax_data = [
        ["Strategy", "His Gross", "Her Gross", "Tax (him)", "Tax (her)", "Total Net", "Annual Saving"],
        ["All income to him", "£50,000", "£0", "£7,486", "£0", "£42,514", "—"],
        ["Equal split £25k each ✓", "£25,000", "£25,000", "£2,486", "£2,486", "£45,028", "+£2,514"],
        ["DB + top-up vs minimum", "£37,811", "£12,189", "£5,048", "£0", "£44,952", "+£2,438"],
    ]
    tt = Table(tax_data, colWidths=[46*mm, 24*mm, 24*mm, 22*mm, 22*mm, 26*mm, W - 164*mm])
    tt.setStyle(tbl_style_default())
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#E8F4F8")),
        ("FONTNAME",   (0, 2), (-1, 2), "Helvetica-Bold"),
        ("TEXTCOLOR",  (-1, 2), (-1, 2), colors.HexColor(GREEN)),
    ]))
    story.append(tt)

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "✓  Recommended approach: Draw his DB1 (£17,811) through him, then top up from his "
        "DC drawdown to £25,000. Draw £25,000 from wife's DC drawdown. This uses both personal "
        "allowances optimally and saves £2,514/year in income tax — worth £50,000+ over 20 years.",
        s["ok"]))

    story.append(PageBreak())

    # ── SECTION 7 — DB PENSION TIMING ───────────────────────────
    story.append(Paragraph("7.  DB Pension 1 — Take at 55 or Defer to 58?", s["h2"]))
    story.append(Paragraph(
        "Your DB Pension 1 becomes available at age 55 — approximately one year from now (2027). "
        "You plan to retire at 58. You have a choice: take the pension immediately at 55 or "
        "defer it to retirement at 58 for an enhancement.",
        s["body"]))

    db_timing_data = [
        ["", "Take at 55", "Defer to 58"],
        ["Annual pension (today's value)", "£16,300/yr", "~£18,900/yr (est. 5%/yr enhancement)"],
        ["Income received before retirement (3 yrs)", "£48,900", "£0"],
        ["Annual difference", "—", "+£2,600/yr for life"],
        ["Break-even period", "—", "~19 years (age 77)"],
        ["Recommendation", "Generally favourable", "Better only if long life expectancy"],
    ]
    dbt = Table(db_timing_data, colWidths=[55*mm, 60*mm, W - 115*mm])
    dbt.setStyle(tbl_style_default())
    story.append(dbt)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "⚠  Action required: Contact the DB1 scheme administrator to obtain the exact actuarial "
        "enhancement factors for late retirement. The general lean is to take it at 55 — you "
        "collect 3 years of income (£48,900) and the break-even for deferral is ~age 77.",
        s["flag"]))

    story.append(Spacer(1, 3 * mm))

    # ── SECTION 8 — RISK FLAGS ───────────────────────────────────
    story.append(Paragraph("8.  Validation Flags & Risk Items", s["h2"]))

    flags = [
        ("⚠  Flag 1 — DC Pot Estimate (£315k vs £382k projected)",
         "Your estimate of £315,000 is approximately £67,000 below the model projection at the same "
         "date. Likely cause: the Aon pot (£135,000) is missing from your own calculation. Once "
         "the transfer completes, the Aegon pot is much larger. Verify this before planning withdrawals."),
        ("⚠  Flag 2 — Aon Transfer: Check Safeguarded Benefits",
         "Before transferring the Aon pot to Aegon, confirm there are no Guaranteed Annuity Rates "
         "(GARs) or defined benefit underpins attached. Losing a GAR can cost tens of thousands. "
         "A regulated pension transfer specialist must advise on transfers over £30,000."),
        ("⚠  Flag 3 — Investment Concentration Risk",
         "30% L&G Global Technology is a highly concentrated, volatile sector fund. 70% Vanguard "
         "LS80 is already 80% equity. Combined, you hold approximately 85–90% global equities "
         "4 years from retirement. A major market correction in 2028–2029 could permanently reduce "
         "your retirement pot. Consider moving 20–30% to lower-risk assets 2–3 years before retirement."),
        ("⚠  Flag 4 — Sequence of Returns Risk in Drawdown",
         "Drawing from a high-equity portfolio in early retirement during a bear market can "
         "permanently damage your pot. Consider holding 2–3 years of DC income in cash or short-dated "
         "bonds as a buffer at the point of retirement. This insulates against poor early returns."),
        ("⚠  Flag 5 — State Pension Age Uncertainty",
         "You and your wife (born ~1972/1973) may be affected by a planned increase in state pension "
         "age to 68. Check your National Insurance records at GOV.UK to confirm full entitlement "
         "(35 qualifying years). Any shortfall can be plugged with voluntary NI contributions (currently "
         "very cost-effective)."),
        ("⚠  Flag 6 — Withdrawal Rate at 8–9%",
         "At 8–9% withdrawal rates, the pot depletes at roughly age 73–77. While DC drawdown "
         "becomes less critical once state pensions begin at 67, exhausting the pot early removes "
         "your financial buffer and leaves you reliant entirely on guaranteed income. Target 6–7% "
         "maximum for a 25–30 year retirement."),
    ]
    for title, body in flags:
        story.append(KeepTogether([
            Paragraph(f"<b>{title}</b><br/>{body}", s["flag"]),
            Spacer(1, 2 * mm),
        ]))

    ok_items = [
        ("✓  Annual Allowance",
         "Your contributions (£2,965/month = £35,580/year) are well within the £60,000 "
         "annual allowance. No action needed."),
        ("✓  Lump Sum Allowance",
         "Your combined PCLS (£131,750 projected) is well within the £268,275 lump sum "
         "allowance. No lifetime allowance concerns."),
        ("✓  Long-term income sustainability",
         "By age 68, guaranteed income (DB + state pensions) covers the inflation-adjusted "
         "£50,000 target. Your DC pot is a supplement, not the sole income source."),
        ("✓  Spouse's pension on DB",
         "All DB pensions carry 50% spouse's pension on death. Your wife is protected."),
    ]
    for title, body in ok_items:
        story.append(KeepTogether([
            Paragraph(f"<b>{title}</b><br/>{body}", s["ok"]),
            Spacer(1, 2 * mm),
        ]))

    story.append(PageBreak())

    # ── SECTION 9 — RECOMMENDED ACTIONS ─────────────────────────
    story.append(Paragraph("9.  Recommended Actions", s["h2"]))

    actions = [
        ["Priority", "Action", "Timescale"],
        ["1 — Urgent", "Check Aon transfer for GARs / safeguarded benefits. "
         "Use a regulated pension transfer specialist.", "Before initiating transfer"],
        ["2 — Soon", "Confirm your DC pot projection — verify whether £315k includes "
         "the Aon pot or just Aegon.", "This month"],
        ["3 — Soon", "Contact DB1 scheme for exact late retirement enhancement factors. "
         "Decide whether to take at 55 (2027) or defer to 58.", "Within 6 months"],
        ["4 — Medium", "Check NI records (GOV.UK). If either of you has gaps, "
         "consider voluntary Class 3 NI contributions.", "Before April 2025 deadline"],
        ["5 — Medium", "Begin de-risking the DC portfolio 2–3 years before retirement "
         "(target ~60–65% equity, 35–40% lower-risk by 2028).", "From 2027–2028"],
        ["6 — Retirement", "Structure drawdown to split income equally across both spouses "
         "(saves ~£2,514/year in tax).", "At retirement in 2030"],
        ["7 — Retirement", "Establish a cash buffer of 2–3 years' DC income (£60–90k) "
         "before commencing drawdown.", "At retirement in 2030"],
        ["8 — Monitor", "Re-run this projection annually as markets and legislation change.",
         "Annual review"],
    ]
    at2 = Table(actions, colWidths=[32*mm, 110*mm, W - 142*mm])
    at2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_LGREY]),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR",  (0, 1), (0, 3), colors.HexColor(RED)),
        ("TEXTCOLOR",  (0, 4), (0, 5), colors.HexColor(GOLD)),
        ("TEXTCOLOR",  (0, 6), (0, -1), colors.HexColor(TEAL)),
        ("FONTNAME",   (0, 1), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(at2)

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=C_GOLD, spaceAfter=6))
    story.append(Paragraph("Disclaimer", s["h3"]))
    story.append(Paragraph(
        "This report has been generated for educational and planning purposes only using the "
        "Finance Skills Claude Code plugin suite (skills: time-value-of-money, tax-efficiency, "
        "savings-goals, investment-policy, liquidity-management). All figures are projections "
        "based on the assumptions stated herein; they are not guarantees of future performance. "
        "UK tax parameters are based on 2024/25 rates and may change. DB pension terms, "
        "enhancement factors, and transfer values should be verified directly with each scheme "
        "administrator. Investment returns are illustrative and not guaranteed. Nothing in this "
        "report constitutes regulated financial advice. You should consult an FCA-authorised "
        "independent financial adviser before making decisions about pension transfers, drawdown "
        "strategy, or retirement planning.",
        s["disclaimer"]))

    doc.build(story)
    print(f"PDF written to: {output_path}")


if __name__ == "__main__":
    build_pdf("/home/user/skills/Pension_Validation_Report.pdf")
