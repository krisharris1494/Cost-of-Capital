"""
International Cost of Capital App
=================================
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, with a labelled snapshot fallback if a site blocks the request):
  1. Industry unlevered betas  - Aswath Damodaran, betas.xls (sheet "Industry Averages")
  2. BBB (Baa2) USD spread     - Aswath Damodaran, ratings.html (large non-financial service firms)
  3. Statutory corporate tax   - OECD Corporate Tax Statistics database (SDMX API, combined CIT rate)
  4. 10-year govt bond yields  - Trading Economics country bond pages

All formulas live in `compute_cost_of_capital()` so they can be checked (or changed
to match the in-class formulas) in one place.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Source URLs
# ---------------------------------------------------------------------------
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_REPORT_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
)
# OECD Corporate Tax Statistics database, dataflow DSD_TAX_CIT@DF_CIT
# Key = REF_AREA.FREQ.MEASURE.TARGETING.UNIT_MEASURE.SECTOR.DIV_TREATMENT.RATE_STRUCTURE.TAX_BASE
# CIT_C = combined (central + sub-central) rate, ST = standard statutory, S13 = general government
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/"
    ".A.CIT_C.ST.PT_INC_TAX.S13...?startPeriod=2015&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 20

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"

# ---------------------------------------------------------------------------
# Countries listed on tradingeconomics.com/bonds -> (TE page slug, OECD ISO3 code)
# ISO3 = None where the OECD database has no rate (tax must be entered manually).
# ---------------------------------------------------------------------------
COUNTRIES = {
    "United States": ("united-states", "USA"),
    "United Kingdom": ("united-kingdom", "GBR"),
    "Japan": ("japan", "JPN"),
    "Australia": ("australia", "AUS"),
    "Germany": ("germany", "DEU"),
    "Brazil": ("brazil", "BRA"),
    "Russia": ("russia", None),
    "India": ("india", "IND"),
    "Canada": ("canada", "CAN"),
    "Italy": ("italy", "ITA"),
    "France": ("france", "FRA"),
    "South Africa": ("south-africa", "ZAF"),
    "China": ("china", "CHN"),
    "Switzerland": ("switzerland", "CHE"),
    "Mexico": ("mexico", "MEX"),
    "Netherlands": ("netherlands", "NLD"),
    "New Zealand": ("new-zealand", "NZL"),
    "Portugal": ("portugal", "PRT"),
    "South Korea": ("south-korea", "KOR"),
    "Spain": ("spain", "ESP"),
    "Greece": ("greece", "GRC"),
    "Turkey": ("turkey", "TUR"),
    "Finland": ("finland", "FIN"),
    "Lithuania": ("lithuania", "LTU"),
    "Norway": ("norway", "NOR"),
    "Poland": ("poland", "POL"),
    "Romania": ("romania", "ROU"),
    "Slovakia": ("slovakia", "SVK"),
    "Slovenia": ("slovenia", "SVN"),
    "Sweden": ("sweden", "SWE"),
    "Hungary": ("hungary", "HUN"),
    "Iceland": ("iceland", "ISL"),
    "Ireland": ("ireland", "IRL"),
    "Austria": ("austria", "AUT"),
    "Belgium": ("belgium", "BEL"),
    "Croatia": ("croatia", "HRV"),
    "Czech Republic": ("czech-republic", "CZE"),
    "Denmark": ("denmark", "DNK"),
    "Peru": ("peru", "PER"),
    "Chile": ("chile", "CHL"),
    "Colombia": ("colombia", "COL"),
    "Singapore": ("singapore", "SGP"),
    "Taiwan": ("taiwan", None),
    "Thailand": ("thailand", "THA"),
    "Vietnam": ("vietnam", "VNM"),
    "Hong Kong": ("hong-kong", "HKG"),
    "Indonesia": ("indonesia", "IDN"),
    "Israel": ("israel", "ISR"),
    "Malaysia": ("malaysia", "MYS"),
    "Pakistan": ("pakistan", "PAK"),
    "Philippines": ("philippines", "PHL"),
    "Zambia": ("zambia", "ZMB"),
    "Kenya": ("kenya", "KEN"),
    "Nigeria": ("nigeria", "NGA"),
}

# ---------------------------------------------------------------------------
# Snapshot fallbacks — used ONLY if a live fetch fails; the app labels them clearly.
# Captured from the live sources on 15 Nov 2026.
# ---------------------------------------------------------------------------
SNAPSHOT_DATE = "2026-11-15"

SNAPSHOT_BETAS_DATE = "2026-01-05"  # "Date updated" cell in betas.xls
SNAPSHOT_BETAS = {
    "Advertising": 0.930086, "Aerospace/Defense": 0.846669, "Air Transport": 0.70405,
    "Apparel": 0.757982, "Auto & Truck": 1.269033, "Auto Parts": 1.021714,
    "Bank (Money Center)": 0.341059, "Banks (Regional)": 0.286516,
    "Beverage (Alcoholic)": 0.613172, "Beverage (Soft)": 0.555671, "Broadcasting": 0.286362,
    "Brokerage & Investment Banking": 0.580849, "Building Materials": 0.930162,
    "Business & Consumer Services": 0.773588, "Cable TV": 0.352392,
    "Chemical (Basic)": 0.580033, "Chemical (Diversified)": 0.366552,
    "Chemical (Specialty)": 0.792227, "Coal & Related Energy": 1.016535,
    "Computer Services": 0.91551, "Computers/Peripherals": 1.305062,
    "Construction Supplies": 1.016068, "Diversified": 0.78893,
    "Drugs (Biotechnology)": 1.034129, "Drugs (Pharmaceutical)": 0.886211,
    "Education": 0.660196, "Electrical Equipment": 1.147795,
    "Electronics (Consumer & Office)": 0.829853, "Electronics (General)": 0.897365,
    "Engineering/Construction": 1.094912, "Entertainment": 0.737184,
    "Environmental & Waste Services": 0.814469, "Farming/Agriculture": 0.81302,
    "Financial Svcs. (Non-bank & Insurance)": 0.318882, "Food Processing": 0.457418,
    "Food Wholesalers": 0.640882, "Furn/Home Furnishings": 0.624788,
    "Green & Renewable Energy": 0.463301, "Healthcare Products": 0.829063,
    "Healthcare Support Services": 0.688916, "Heathcare Information and Technology": 0.991301,
    "Homebuilding": 0.78496, "Hospitals/Healthcare Facilities": 0.55173,
    "Hotel/Gaming": 0.832251, "Household Products": 0.717816,
    "Information Services": 0.737177, "Insurance (General)": 0.56364,
    "Insurance (Life)": 0.427156, "Insurance (Prop/Cas.)": 0.435656,
    "Investments & Asset Management": 0.529716, "Machinery": 0.867976,
    "Metals & Mining": 0.963643, "Office Equipment & Services": 0.980604,
    "Oil/Gas (Integrated)": 0.271219, "Oil/Gas (Production and Exploration)": 0.56276,
    "Oil/Gas Distribution": 0.465076, "Oilfield Svcs/Equip.": 0.743039,
    "Packaging & Container": 0.723069, "Paper/Forest Products": 0.721553, "Power": 0.310024,
    "Precious Metals": 0.793243, "Publishing & Newspapers": 0.477307, "R.E.I.T.": 0.392904,
    "Real Estate (Development)": 0.478288, "Real Estate (General/Diversified)": 0.577859,
    "Real Estate (Operations & Services)": 0.814892, "Recreation": 0.695091,
    "Reinsurance": 0.438409, "Restaurant/Dining": 0.76742, "Retail (Automotive)": 0.698433,
    "Retail (Building Supply)": 1.307014, "Retail (Distributors)": 0.782683,
    "Retail (General)": 0.759964, "Retail (Grocery and Food)": 0.804751,
    "Retail (REITs)": 0.436173, "Retail (Special Lines)": 0.948783, "Rubber& Tires": 0.143534,
    "Semiconductor": 1.489258, "Semiconductor Equip": 1.348073,
    "Shipbuilding & Marine": 0.644013, "Shoe": 0.933675, "Software (Entertainment)": 1.012781,
    "Software (Internet)": 1.546064, "Software (System & Application)": 1.225392,
    "Steel": 0.903514, "Telecom (Wireless)": 0.387259, "Telecom. Equipment": 0.863491,
    "Telecom. Services": 0.365434, "Tobacco": 0.67759, "Transportation": 0.675311,
    "Transportation (Railroads)": 0.806948, "Trucking": 0.850418,
    "Utility (General)": 0.148613, "Utility (Water)": 0.281177,
    "Total Market": 0.72173, "Total Market (without financials)": 0.877517,
}

SNAPSHOT_SPREAD = 0.0111            # Baa2/BBB, large non-financial service firms
SNAPSHOT_SPREAD_DATE = "January 2026"

# OECD combined statutory CIT rate, % (latest year: 2026 except COL/ISR/TUR = 2025)
SNAPSHOT_TAX = {
    "USA": (25.5285, 2026), "GBR": (25, 2026), "JPN": (29.74, 2026), "AUS": (30, 2026),
    "DEU": (30.133026, 2026), "BRA": (34, 2026), "IND": (25.17, 2026), "CAN": (26, 2026),
    "ITA": (27.81, 2026), "FRA": (36.13, 2026), "ZAF": (27, 2026), "CHN": (25, 2026),
    "CHE": (19.471871, 2026), "MEX": (30, 2026), "NLD": (25.8, 2026), "NZL": (28, 2026),
    "PRT": (29.5, 2026), "KOR": (27.5, 2026), "ESP": (25, 2026), "GRC": (22, 2026),
    "TUR": (25, 2025), "FIN": (20, 2026), "LTU": (17, 2026), "NOR": (22, 2026),
    "POL": (19, 2026), "ROU": (16, 2026), "SVK": (24, 2026), "SVN": (22, 2026),
    "SWE": (20.6, 2026), "HUN": (9, 2026), "ISL": (20, 2026), "IRL": (12.5, 2026),
    "AUT": (23, 2026), "BEL": (25, 2026), "HRV": (18, 2026), "CZE": (21, 2026),
    "DNK": (22, 2026), "PER": (29.5, 2026), "CHL": (27, 2026), "COL": (35, 2025),
    "SGP": (17, 2026), "THA": (20, 2026), "VNM": (20, 2026), "HKG": (16.5, 2026),
    "IDN": (22, 2026), "ISR": (23, 2025), "MYS": (24, 2026), "PAK": (29, 2026),
    "PHL": (25, 2026), "ZMB": (30, 2026), "KEN": (30, 2026), "NGA": (30, 2026),
}

# Trading Economics 10Y yields, % (from tradingeconomics.com/bonds; dated Nov 13, 2026
# except Peru = Nov 12, 2026)
SNAPSHOT_YIELDS = {
    "United States": 5.1450, "United Kingdom": 5.3377, "Japan": 2.8616, "Australia": 5.1290,
    "Germany": 3.3762, "Brazil": 15.3350, "Russia": 16.6830, "India": 7.3120,
    "Canada": 3.8560, "Italy": 4.4370, "France": 4.9210, "South Africa": 8.6750,
    "China": 1.6181, "Switzerland": 0.5626, "Mexico": 9.3080, "Netherlands": 3.4768,
    "New Zealand": 4.7462, "Portugal": 3.8186, "South Korea": 3.9870, "Spain": 3.9442,
    "Greece": 4.2640, "Turkey": 33.5200, "Finland": 3.7611, "Lithuania": 4.3250,
    "Norway": 4.3842, "Poland": 6.3350, "Romania": 7.1200, "Slovakia": 4.3050,
    "Slovenia": 3.9140, "Sweden": 3.0980, "Hungary": 5.5250, "Iceland": 6.8100,
    "Ireland": 3.5390, "Austria": 3.6100, "Belgium": 4.3550, "Croatia": 3.8668,
    "Czech Republic": 5.2220, "Denmark": 3.1693, "Peru": 6.2600, "Chile": 6.0100,
    "Colombia": 12.6980, "Singapore": 2.3300, "Taiwan": 1.8600, "Thailand": 1.9950,
    "Vietnam": 4.5730, "Hong Kong": 3.9940, "Indonesia": 7.6070, "Israel": 4.1830,
    "Malaysia": 3.8630, "Pakistan": 12.6040, "Philippines": 7.7670, "Zambia": 14.7400,
    "Kenya": 12.5000, "Nigeria": 16.5980,
}
SNAPSHOT_YIELD_DATE = "Nov 13, 2026 (Peru: Nov 12, 2026)"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Data fetchers (cached for 6 hours; the Refresh button clears the cache)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_betas() -> dict:
    """Damodaran betas.xls -> DataFrame[Industry, Unlevered beta]."""
    try:
        r = requests.get(BETAS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Industry Averages",
                            header=None, engine="xlrd")
        # Header row = the row whose first cell is "Industry Name"
        hdr_idx = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Industry Name"][0]
        headers = [str(h).strip() for h in raw.iloc[hdr_idx]]
        # Exact match "Unlevered beta" (not "Unlevered beta corrected for cash")
        ub_col = next(i for i, h in enumerate(headers) if h.lower() == "unlevered beta")
        body = raw.iloc[hdr_idx + 1:, [0, ub_col]].copy()
        body.columns = ["Industry", "Unlevered beta"]
        body = body.dropna(subset=["Industry"])
        body["Industry"] = body["Industry"].astype(str).str.strip()
        body = body[body["Industry"] != ""]
        body["Unlevered beta"] = pd.to_numeric(body["Unlevered beta"], errors="coerce")
        body = body.dropna(subset=["Unlevered beta"]).reset_index(drop=True)

        # "Date updated:" cell (row 0, col 1): datetime or Excel serial number
        date_val = raw.iloc[0, 1]
        if isinstance(date_val, (int, float)):
            date_str = (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(date_val))).strftime("%Y-%m-%d")
        else:
            date_str = pd.to_datetime(date_val).strftime("%Y-%m-%d")
        return {"df": body, "date": date_str, "live": True, "retrieved": _now(), "error": None}
    except Exception as e:  # noqa: BLE001
        df = pd.DataFrame(list(SNAPSHOT_BETAS.items()), columns=["Industry", "Unlevered beta"])
        return {"df": df, "date": SNAPSHOT_BETAS_DATE, "live": False,
                "retrieved": SNAPSHOT_DATE, "error": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_bbb_spread() -> dict:
    """Damodaran ratings.html -> Baa2/BBB spread for large non-financial service firms."""
    try:
        r = requests.get(RATINGS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        spread = None
        # The large non-financial firms block is the LEFT-hand set of columns, so the
        # first "Baa2/BBB" cell in a row belongs to it; the spread is the next cell.
        for tr in soup.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if "Baa2/BBB" in cells:
                i = cells.index("Baa2/BBB")
                spread = float(cells[i + 1].replace("%", "")) / 100
                break
        if spread is None:
            raise ValueError("Baa2/BBB row not found")
        text = soup.get_text(" ", strip=True)
        m = re.search(r"Data used is as of\s+([A-Za-z]+\s+\d{4})", text)
        date_str = m.group(1) if m else "date not stated"
        return {"value": spread, "date": date_str, "live": True, "retrieved": _now(), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"value": SNAPSHOT_SPREAD, "date": SNAPSHOT_SPREAD_DATE, "live": False,
                "retrieved": SNAPSHOT_DATE, "error": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_tax_rates() -> dict:
    """OECD Corporate Tax Statistics (SDMX) -> {ISO3: (rate %, year)} latest combined statutory CIT."""
    try:
        r = requests.get(OECD_API_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df = df[(df["MEASURE"] == "CIT_C") & (df["TARGETING"] == "ST") & (df["SECTOR"] == "S13")]
        df = df.dropna(subset=["OBS_VALUE"])
        df["TIME_PERIOD"] = df["TIME_PERIOD"].astype(int)
        latest = df.sort_values("TIME_PERIOD").groupby("REF_AREA").tail(1)
        rates = {row.REF_AREA: (float(row.OBS_VALUE), int(row.TIME_PERIOD)) for row in latest.itertuples()}
        if "USA" not in rates:
            raise ValueError("USA missing from OECD response")
        return {"rates": rates, "live": True, "retrieved": _now(), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"rates": dict(SNAPSHOT_TAX), "live": False, "retrieved": SNAPSHOT_DATE, "error": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_yield(country: str) -> dict:
    """Trading Economics country page -> latest 10Y government bond yield (%) and its date."""
    slug = COUNTRIES[country][0]
    url = TE_COUNTRY_URL.format(slug=slug)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        value, date_str = None, None

        # (a) Meta description, e.g. "... rose to 5.15% on November 13, 2026, ..."
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            m = re.search(r"(-?\d+(?:\.\d+)?)%\s+on\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", meta["content"])
            if m:
                value, date_str = float(m.group(1)), m.group(2)

        # (b) "Bonds | Yield | ... | Date" table, row whose label contains "10Y" (more precise value)
        for table in soup.find_all("table"):
            th = table.find("th")
            if th and th.get_text(strip=True).lower().startswith("bonds"):
                for tr in table.find_all("tr"):
                    cells = [c.get_text(strip=True) for c in tr.find_all("td")]
                    if len(cells) >= 2 and "10Y" in cells[0]:
                        try:
                            value = float(cells[1])
                        except ValueError:
                            pass
                        if not date_str and cells:
                            date_str = cells[-1]
                        break
                break

        if value is None:
            raise ValueError("10Y yield not found on page")
        return {"value": value / 100, "date": date_str or "date not stated", "live": True,
                "retrieved": _now(), "url": url, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"value": SNAPSHOT_YIELDS[country] / 100, "date": SNAPSHOT_YIELD_DATE, "live": False,
                "retrieved": SNAPSHOT_DATE, "url": url, "error": str(e)}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_cost_of_capital(beta_u: float, tax: float, debt_share: float, erp: float,
                            y_us: float, y_fc: float, spread_usd: float,
                            spread_fc_manual: float | None = None,
                            method: str = "multiplicative") -> dict:
    """All rates are decimals (0.05 = 5%).

    USD:
        D/E          = w_d / (1 - w_d)
        beta_L       = beta_u * (1 + (1 - t) * D/E)                       (Hamada)
        k_e(USD)     = y_US + beta_L * ERP                                (CAPM)
        k_d(USD)     = y_US + BBB spread(USD)
        WACC(USD)    = (1 - w_d) * k_e(USD) + w_d * k_d(USD) * (1 - t)

    Foreign currency (FC), "multiplicative" (relative interest-rate / Fisher parity):
        (1 + k_e(FC)) = (1 + k_e(USD)) * (1 + y_FC) / (1 + y_US)
        (1 + k_d(FC)) = (1 + k_d(USD)) * (1 + y_FC) / (1 + y_US)
        => auto FC spread = k_d(FC) - y_FC = spread(USD) * (1 + y_FC) / (1 + y_US)
    Foreign currency, "additive" (yield-differential approximation):
        k_e(FC) = k_e(USD) + (y_FC - y_US) = y_FC + beta_L * ERP
        k_d(FC) = k_d(USD) + (y_FC - y_US) => auto FC spread = spread(USD)
    If a manual FC spread is given: k_d(FC) = y_FC + manual spread.
        WACC(FC) = (1 - w_d) * k_e(FC) + w_d * k_d(FC) * (1 - t)
    """
    w_d = debt_share
    w_e = 1 - w_d
    de = w_d / w_e if w_e > 0 else float("inf")
    beta_l = beta_u * (1 + (1 - tax) * de)

    ke_usd = y_us + beta_l * erp
    kd_usd = y_us + spread_usd

    if method == "multiplicative":
        ratio = (1 + y_fc) / (1 + y_us)
        ke_fc = (1 + ke_usd) * ratio - 1
        spread_fc_auto = spread_usd * ratio
    else:
        ke_fc = ke_usd + (y_fc - y_us)
        spread_fc_auto = spread_usd

    spread_fc = spread_fc_manual if spread_fc_manual is not None else spread_fc_auto
    kd_fc = y_fc + spread_fc

    wacc_usd = w_e * ke_usd + w_d * kd_usd * (1 - tax)
    wacc_fc = w_e * ke_fc + w_d * kd_fc * (1 - tax)

    return {
        "D/E": de, "beta_L": beta_l,
        "rf_usd": y_us, "rf_fc": y_fc,
        "spread_usd": spread_usd, "spread_fc": spread_fc, "spread_fc_auto": spread_fc_auto,
        "ke_usd": ke_usd, "ke_fc": ke_fc,
        "kd_usd": kd_usd, "kd_fc": kd_fc,
        "kd_at_usd": kd_usd * (1 - tax), "kd_at_fc": kd_fc * (1 - tax),
        "wacc_usd": wacc_usd, "wacc_fc": wacc_fc,
    }


def pct(x: float, d: int = 2) -> str:
    return f"{x * 100:.{d}f}%"


def pp(x: float) -> str:
    """Difference in percentage points, without a '-0.00'."""
    v = round(x * 100, 2) + 0.0
    return f"{v:+.2f} pp"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="International Cost of Capital", page_icon="ᚠ", layout="wide")

# ---------------------------------------------------------------------------
# Norse rune theme (colors/fonts also set in .streamlit/config.toml)
# ---------------------------------------------------------------------------
GOLD, FROST, EMBER, BONE = "#d4a24c", "#8ec5e6", "#c8552b", "#e8dcc4"
FUTHARK = "ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ"  # Elder Futhark, 24 runes
_RUNE_MAP = {"th": "ᚦ", "ng": "ᛜ", "a": "ᚨ", "b": "ᛒ", "c": "ᚲ", "d": "ᛞ", "e": "ᛖ", "f": "ᚠ", "g": "ᚷ",
             "h": "ᚺ", "i": "ᛁ", "j": "ᛃ", "k": "ᚲ", "l": "ᛚ", "m": "ᛗ", "n": "ᚾ", "o": "ᛟ", "p": "ᛈ",
             "q": "ᚲ", "r": "ᚱ", "s": "ᛊ", "t": "ᛏ", "u": "ᚢ", "v": "ᚹ", "w": "ᚹ", "x": "ᚲᛊ", "y": "ᛁ",
             "z": "ᛉ", " ": " ᛫ "}


def to_runes(text: str) -> str:
    """Approximate Latin -> Elder Futhark transliteration (decorative only)."""
    text, out, i = text.lower(), "", 0
    while i < len(text):
        if text[i:i + 2] in _RUNE_MAP:
            out += _RUNE_MAP[text[i:i + 2]]; i += 2
        else:
            out += _RUNE_MAP.get(text[i], ""); i += 1
    return out


def rune_circle_svg(size: int = 132) -> str:
    """Original emblem: a ring of the 24 Elder Futhark runes around fehu (ᚠ, 'wealth')."""
    return f"""
<svg class="rune-emblem" width="{size}" height="{size}" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="ember" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{EMBER}" stop-opacity="0.55"/>
      <stop offset="70%" stop-color="{EMBER}" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="{EMBER}" stop-opacity="0"/>
    </radialGradient>
    <path id="ring" d="M100,100 m-72,0 a72,72 0 1,1 144,0 a72,72 0 1,1 -144,0"/>
  </defs>
  <circle cx="100" cy="100" r="98" fill="url(#ember)"/>
  <circle cx="100" cy="100" r="92" fill="#15171b" stroke="{GOLD}" stroke-width="2.5"/>
  <circle cx="100" cy="100" r="86" fill="none" stroke="{GOLD}" stroke-width="0.8" stroke-opacity="0.6"/>
  <circle cx="100" cy="100" r="58" fill="none" stroke="{GOLD}" stroke-width="0.8" stroke-opacity="0.6"/>
  <text font-family="'Noto Sans Runic', serif" font-size="15" fill="{GOLD}" letter-spacing="2.2">
    <textPath href="#ring" startOffset="0">{FUTHARK}</textPath>
  </text>
  <circle cx="100" cy="100" r="44" fill="#0d0f12" stroke="{FROST}" stroke-width="1.5" stroke-opacity="0.8"/>
  <text x="100" y="121" text-anchor="middle" font-family="'Noto Sans Runic', serif" font-size="62"
        fill="{FROST}" class="rune-glow">ᚠ</text>
</svg>"""


st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Cinzel+Decorative:wght@700&family=Noto+Sans+Runic&family=Spectral:wght@400;600&display=swap');

:root {{ --gold:{GOLD}; --frost:{FROST}; --ember:{EMBER}; --bone:{BONE}; }}

/* Carved-stone backdrop with a faint forge glow */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(ellipse at 15% -10%, rgba(200,85,43,0.16), transparent 45%),
    radial-gradient(ellipse at 95% 0%, rgba(142,197,230,0.10), transparent 40%),
    repeating-linear-gradient(135deg, rgba(255,255,255,0.012) 0 2px, transparent 2px 9px),
    #0d0f12;
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #15171c 0%, #0f1114 100%);
  border-right: 1px solid rgba(212,162,76,0.35);
}}
[data-testid="stSidebar"] h2 {{
  color: var(--gold); letter-spacing: .12em; font-size: 1.05rem; text-transform: uppercase;
  border-bottom: 1px solid rgba(212,162,76,0.35); padding-bottom: .35rem;
}}
h1, h2, h3, h4 {{ font-family: 'Cinzel', serif !important; letter-spacing: .06em; }}
h3, h4 {{ color: var(--gold) !important; }}

/* Hero banner */
.rune-hero {{
  display:flex; align-items:center; gap:1.6rem; padding:1.2rem 1.6rem; margin-bottom:.6rem;
  border:1px solid rgba(212,162,76,0.55); border-radius:4px;
  background: linear-gradient(180deg, rgba(27,30,35,0.92), rgba(13,15,18,0.92));
  box-shadow: inset 0 0 0 4px #0d0f12, inset 0 0 0 5px rgba(212,162,76,0.25), 0 0 40px rgba(200,85,43,0.12);
}}
.rune-hero h1 {{
  font-family:'Cinzel Decorative','Cinzel',serif !important; color:var(--bone); margin:0; padding:0;
  font-size:2.3rem; text-shadow: 0 0 18px rgba(212,162,76,0.35);
}}
.rune-band, .rune-translit, .rune-divider, .rune {{ font-family:'Noto Sans Runic', serif; }}
.rune-band {{ color:var(--gold); opacity:.55; letter-spacing:.55em; font-size:.9rem; white-space:nowrap; overflow:hidden; }}
.rune-translit {{ color:var(--frost); letter-spacing:.3em; font-size:1.05rem; margin:.15rem 0 .35rem;
  text-shadow:0 0 10px rgba(142,197,230,0.45); }}
.rune-sub {{ color:#b9ad95; margin:0; font-style:italic; }}
.rune-emblem {{ flex-shrink:0; filter: drop-shadow(0 0 10px rgba(200,85,43,0.35)); }}
.rune-glow {{ filter: drop-shadow(0 0 6px {FROST}); }}
.rune-divider {{ text-align:center; color:var(--gold); opacity:.6; letter-spacing:.8em; margin:1.2rem 0 .6rem;
  background: linear-gradient(90deg, transparent, rgba(212,162,76,.45), transparent) center/100% 1px no-repeat; }}
.rune-divider span {{ background:#0d0f12; padding:0 .8rem; }}

/* Currency panel headers */
.realm {{ font-family:'Cinzel',serif; font-size:1.25rem; letter-spacing:.1em; padding:.35rem .8rem; margin-bottom:.5rem;
  border-left:3px solid; background:linear-gradient(90deg, rgba(255,255,255,0.04), transparent); }}
.realm.usd {{ color:var(--gold); border-color:var(--gold); }}
.realm.fc  {{ color:var(--frost); border-color:var(--frost); }}
.realm .rune {{ font-size:1.5rem; margin-right:.5rem; }}

/* Metrics as carved tablets */
[data-testid="stMetric"] {{
  background: linear-gradient(180deg, #1d2026, #14161a);
  border:1px solid rgba(212,162,76,0.45); border-radius:3px; padding:.8rem 1rem;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), inset 0 -8px 18px rgba(0,0,0,0.35);
}}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ white-space:normal !important;
  overflow:visible !important; text-overflow:clip !important; }}
[data-testid="stMetricLabel"] {{ min-height:2.7rem; align-items:flex-start; }}
[data-testid="stMetricLabel"] p {{ font-family:'Cinzel',serif; letter-spacing:.04em;
  font-size:.82rem !important; color:#b9ad95; line-height:1.25; }}
[data-testid="stAlertContainer"] {{ background:rgba(200,85,43,0.12) !important; border:1px solid rgba(200,85,43,0.55);
  border-radius:3px; }}
[data-testid="stAlertContainer"] p {{ color:var(--bone) !important; }}
[data-testid="stMetricValue"] {{ font-family:'Cinzel',serif; color:var(--bone); text-shadow:0 0 12px rgba(212,162,76,0.25); }}
[data-testid="stMetricDelta"] {{ color:#9aa5ad !important; }}

/* Tabs */
[data-testid="stTab"] p {{ font-family:'Cinzel',serif; letter-spacing:.08em; font-size:.95rem; }}
[data-testid="stTab"][aria-selected="true"] p {{ color:var(--gold); text-shadow:0 0 10px rgba(212,162,76,.5); }}

/* Buttons */
.stButton > button, [data-testid="stDownloadButton"] button {{
  font-family:'Cinzel',serif; letter-spacing:.08em; border:1px solid var(--gold) !important;
  background:linear-gradient(180deg, #2a2418, #17140e) !important; color:var(--bone) !important;
}}
.stButton > button:hover, [data-testid="stDownloadButton"] button:hover {{
  box-shadow:0 0 14px rgba(212,162,76,.45); color:#fff !important;
}}
[data-testid="stExpander"] {{ border-color: rgba(212,162,76,0.35) !important; }}
blockquote {{ border-left-color: var(--ember) !important; }}
</style>
""", unsafe_allow_html=True)


def rune_divider(runes: str = "ᛟ ᚠ ᛟ") -> None:
    st.markdown(f'<div class="rune-divider"><span>{runes}</span></div>', unsafe_allow_html=True)


hero_l, hero_r = st.columns([5, 1], vertical_alignment="center")
with hero_l:
    st.markdown(f"""
<div class="rune-hero">
  {rune_circle_svg()}
  <div style="min-width:0">
    <div class="rune-band">{FUTHARK}</div>
    <h1>International Cost of Capital</h1>
    <div class="rune-translit">{to_runes("cost of capital")}</div>
    <p class="rune-sub">Project cost of equity, cost of debt and WACC in USD vs. the selected country's currency.</p>
  </div>
</div>""", unsafe_allow_html=True)
with hero_r:
    if st.button("ᛃ  Refresh data", width="stretch",
                 help="Jera (ᛃ), the rune of the turning year. Clears the cache and re-fetches all sources now."):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Consulting the runes: Damodaran, OECD and Trading Economics…"):
    betas = fetch_betas()
    spread_d = fetch_bbb_spread()
    tax_d = fetch_tax_rates()

beta_df = betas["df"]
industries = beta_df["Industry"].tolist()
country_list = list(COUNTRIES.keys())

# ----------------------------- Sidebar -------------------------------------
with st.sidebar:
    st.header("ᛗ Project settings")
    industry = st.selectbox("Industry (Damodaran, U.S.)", industries,
                            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
    country = st.selectbox("Target country", country_list, index=country_list.index(DEFAULT_COUNTRY))

    erp = st.slider("Equity risk premium (%)", 0.0, 15.0, 6.5, 0.1) / 100
    debt_share = st.slider("Target debt share D/(D+E) (%)", 0.0, 90.0, 30.0, 1.0) / 100

    tax_choice = st.radio("Project tax rate", ["U.S.", "Selected country"], index=0, horizontal=True,
                          help="The same tax rate is used for both the USD and foreign-currency calculations.")

    method_label = st.radio(
        "Currency conversion method",
        ["Multiplicative (parity)", "Additive (yield differential)"], index=0,
        help="Multiplicative: (1+k_FC) = (1+k_USD)(1+y_FC)/(1+y_US). "
             "Additive: k_FC = k_USD + (y_FC − y_US). Pick the one used in class.")
    method = "multiplicative" if method_label.startswith("Multiplicative") else "additive"

with st.spinner("Reading the bond yields…"):
    y_us_d = fetch_yield("United States")
    y_fc_d = fetch_yield(country)

# Fetched values
fetched_beta = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0])
us_tax_tuple = tax_d["rates"].get("USA")
fc_iso = COUNTRIES[country][1]
fc_tax_tuple = tax_d["rates"].get(fc_iso) if fc_iso else None

with st.sidebar:
    st.header("ᚦ Manual overrides")
    st.caption("Toggle on to replace a fetched value with your own input.")

    ov_beta = st.toggle("Unlevered beta", False)
    beta_u = (st.number_input("Unlevered beta", value=round(fetched_beta, 4), step=0.01, format="%.4f")
              if ov_beta else fetched_beta)

    ov_ustax = st.toggle("U.S. corporate tax rate", False)
    us_tax = (st.number_input("U.S. tax rate (%)", value=round(us_tax_tuple[0], 2), step=0.5, format="%.2f") / 100
              if ov_ustax else us_tax_tuple[0] / 100)

    fc_missing = fc_tax_tuple is None
    ov_fctax = st.toggle(f"{country} corporate tax rate", fc_missing, disabled=fc_missing,
                         help="No OECD rate is available for this country, so enter one." if fc_missing else None)
    default_fc_tax = fc_tax_tuple[0] if fc_tax_tuple else us_tax_tuple[0]
    fc_tax = (st.number_input(f"{country} tax rate (%)", value=round(default_fc_tax, 2), step=0.5, format="%.2f") / 100
              if (ov_fctax or fc_missing) else fc_tax_tuple[0] / 100)

    ov_spread = st.toggle("USD BBB spread", False)
    spread_usd = (st.number_input("USD BBB spread (%)", value=round(spread_d["value"] * 100, 2), step=0.05, format="%.2f") / 100
                  if ov_spread else spread_d["value"])

    ov_yus = st.toggle("U.S. 10Y government yield", False)
    y_us = (st.number_input("U.S. 10Y yield (%)", value=round(y_us_d["value"] * 100, 4), step=0.05, format="%.4f") / 100
            if ov_yus else y_us_d["value"])

    ov_yfc = st.toggle(f"{country} 10Y government yield", False)
    y_fc = (st.number_input(f"{country} 10Y yield (%)", value=round(y_fc_d["value"] * 100, 4), step=0.05, format="%.4f") / 100
            if ov_yfc else y_fc_d["value"])
    # If the selected country IS the U.S., keep the two yields consistent
    if country == "United States" and not ov_yfc:
        y_fc = y_us

    ov_spread_fc = st.toggle(f"{country} BBB spread (local currency)", False,
                             help="Off = auto-calculated from the USD spread.")
    # auto value for display / default
    _auto = compute_cost_of_capital(beta_u, us_tax, debt_share, erp, y_us, y_fc, spread_usd, None, method)["spread_fc_auto"]
    spread_fc_manual = (st.number_input(f"{country} BBB spread (%)", value=round(_auto * 100, 4), step=0.05, format="%.4f") / 100
                        if ov_spread_fc else None)
    if not ov_spread_fc:
        st.caption(f"Auto-calculated {country} BBB spread: **{pct(_auto, 3)}**")

project_tax = us_tax if tax_choice == "U.S." else fc_tax
res = compute_cost_of_capital(beta_u, project_tax, debt_share, erp, y_us, y_fc,
                              spread_usd, spread_fc_manual, method)

# Data-status banner
fallbacks = [n for n, d in [("Damodaran betas", betas), ("Damodaran BBB spread", spread_d),
                            ("OECD tax rates", tax_d), ("U.S. yield", y_us_d), (f"{country} yield", y_fc_d)]
             if not d["live"]]
if fallbacks:
    st.warning("Live fetch failed for: **" + ", ".join(fallbacks) + f"**. Showing the snapshot captured on "
               f"{SNAPSHOT_DATE} instead (see *Data sources*). Use **Refresh data** to retry, or enter manual values.")
if fc_missing:
    st.info(f"The OECD database has no corporate tax rate for {country}; enter one under *Manual overrides*.")

# ----------------------------- Results -------------------------------------
tab_res, tab_all, tab_src, tab_assump = st.tabs(
    ["ᚠ Results", "ᛗ All-industry comparison", "ᚨ Data sources", "ᛞ Assumptions & formulas"])

with tab_res:
    st.subheader(f"{industry} ᛫ USD vs. {country} currency")
    st.caption(f"Project tax rate: **{pct(project_tax)}** ({tax_choice}{'' if tax_choice == 'U.S.' else ' — ' + country}) · "
               f"ERP **{pct(erp, 1)}** · Debt share **{pct(debt_share, 0)}** · "
               f"Unlevered β **{beta_u:.4f}** → Levered β **{res['beta_L']:.4f}** · Method: {method_label}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="realm usd"><span class="rune">ᚠ</span>USD</div>', unsafe_allow_html=True)
        st.caption("Base currency")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(res["ke_usd"]))
        m2.metric("Pre-tax cost of debt", pct(res["kd_usd"]))
        m3.metric("WACC", pct(res["wacc_usd"]))
    with c2:
        st.markdown(f'<div class="realm fc"><span class="rune">ᚱ</span>{country} currency</div>', unsafe_allow_html=True)
        st.caption("Change vs. USD shown in percentage points (pp)")
        m1, m2, m3 = st.columns(3)
        m1.metric("Cost of equity", pct(res["ke_fc"]), delta=pp(res["ke_fc"] - res["ke_usd"]), delta_color="off")
        m2.metric("Pre-tax cost of debt", pct(res["kd_fc"]), delta=pp(res["kd_fc"] - res["kd_usd"]), delta_color="off")
        m3.metric("WACC", pct(res["wacc_fc"]), delta=pp(res["wacc_fc"] - res["wacc_usd"]), delta_color="off")

    detail = pd.DataFrame({
        "Component": ["10Y government yield (risk-free)", "Unlevered beta", "D/E", "Levered beta",
                      "Equity risk premium", "Cost of equity", "BBB spread", "Pre-tax cost of debt",
                      "Tax rate", "After-tax cost of debt", "Equity weight", "Debt weight", "WACC"],
        "USD": [pct(res["rf_usd"], 3), f"{beta_u:.4f}", f"{res['D/E']:.4f}", f"{res['beta_L']:.4f}", pct(erp),
                pct(res["ke_usd"]), pct(res["spread_usd"], 3), pct(res["kd_usd"]), pct(project_tax),
                pct(res["kd_at_usd"]), pct(1 - debt_share, 0), pct(debt_share, 0), pct(res["wacc_usd"])],
        f"{country} currency": [pct(res["rf_fc"], 3), f"{beta_u:.4f}", f"{res['D/E']:.4f}", f"{res['beta_L']:.4f}",
                                pct(erp), pct(res["ke_fc"]),
                                pct(res["spread_fc"], 3) + (" (manual)" if spread_fc_manual is not None else " (auto)"),
                                pct(res["kd_fc"]), pct(project_tax), pct(res["kd_at_fc"]), pct(1 - debt_share, 0),
                                pct(debt_share, 0), pct(res["wacc_fc"])],
    })
    st.dataframe(detail, hide_index=True, width="stretch")

    # Downloadable results
    inputs_df = pd.DataFrame({
        "Input": ["Industry", "Target country", "Unlevered beta", "Equity risk premium", "Debt share",
                  "Project tax choice", "Project tax rate", "U.S. tax rate", f"{country} tax rate",
                  "USD BBB spread", f"{country} BBB spread", "U.S. 10Y yield", f"{country} 10Y yield",
                  "Conversion method", "Generated"],
        "Value": [industry, country, round(beta_u, 6), erp, debt_share, tax_choice, project_tax, us_tax, fc_tax,
                  spread_usd, res["spread_fc"], y_us, y_fc, method_label, _now()],
        "Overridden?": ["", "", ov_beta, "", "", "", "", ov_ustax, ov_fctax or fc_missing, ov_spread,
                        spread_fc_manual is not None, ov_yus, ov_yfc, "", ""],
    })
    out_df = pd.DataFrame({
        "Metric": ["Levered beta", "Cost of equity", "Pre-tax cost of debt", "After-tax cost of debt", "WACC"],
        "USD": [res["beta_L"], res["ke_usd"], res["kd_usd"], res["kd_at_usd"], res["wacc_usd"]],
        f"{country} currency": [res["beta_L"], res["ke_fc"], res["kd_fc"], res["kd_at_fc"], res["wacc_fc"]],
    })

with tab_all:
    st.subheader(f"All industries ᛫ USD vs. {country} currency")
    st.caption("Uses each industry's fetched unlevered beta with the current tax rate, ERP, debt share, yields and "
               "spreads. (The unlevered-beta override applies only to the selected industry.)")
    rows = []
    for ind, bu in zip(beta_df["Industry"], beta_df["Unlevered beta"]):
        b = beta_u if ind == industry else float(bu)
        r_ = compute_cost_of_capital(b, project_tax, debt_share, erp, y_us, y_fc, spread_usd, spread_fc_manual, method)
        rows.append({"Industry": ind, "Unlevered beta": b, "Levered beta": r_["beta_L"],
                     "Cost of equity (USD)": r_["ke_usd"], f"Cost of equity ({country})": r_["ke_fc"],
                     "Cost of debt (USD)": r_["kd_usd"], f"Cost of debt ({country})": r_["kd_fc"],
                     "WACC (USD)": r_["wacc_usd"], f"WACC ({country})": r_["wacc_fc"]})
    all_df = pd.DataFrame(rows)

    sort_col = st.selectbox("Sort by", [c for c in all_df.columns if c != "Industry"],
                            index=list(all_df.columns).index("WACC (USD)") - 1)
    shown = all_df.sort_values(sort_col, ascending=False).reset_index(drop=True)
    pct_cols = [c for c in all_df.columns if c not in ("Industry", "Unlevered beta", "Levered beta")]
    st.dataframe(
        shown.style.format({**{c: "{:.2%}" for c in pct_cols}, "Unlevered beta": "{:.4f}", "Levered beta": "{:.4f}"})
        .apply(lambda r: ["background-color: rgba(200, 85, 43, 0.30)" if r["Industry"] == industry else "" for _ in r],
               axis=1),
        hide_index=True, width="stretch", height=420)

    chart_df = all_df.melt(id_vars="Industry", value_vars=["WACC (USD)", f"WACC ({country})"],
                           var_name="Currency", value_name="WACC")
    order = all_df.sort_values("WACC (USD)", ascending=False)["Industry"].tolist()
    chart = (alt.Chart(chart_df)
             .mark_bar()
             .encode(y=alt.Y("Industry:N", sort=order, title=None),
                     x=alt.X("WACC:Q", axis=alt.Axis(format="%"), title="WACC"),
                     color=alt.Color("Currency:N", legend=alt.Legend(orient="top", title=None),
                                     scale=alt.Scale(domain=["WACC (USD)", f"WACC ({country})"], range=[GOLD, FROST])),
                     yOffset="Currency:N",
                     tooltip=["Industry", "Currency", alt.Tooltip("WACC:Q", format=".2%")])
             .properties(height=max(400, 22 * len(order)))
             .configure(background="transparent", font="Spectral")
             .configure_axis(labelColor=BONE, titleColor=GOLD, gridColor="#2a2d33", domainColor="#4a3f2c",
                             titleFont="Cinzel", labelFontSize=11)
             .configure_legend(labelColor=BONE, labelFont="Cinzel")
             .configure_view(stroke=None))
    st.altair_chart(chart, width="stretch", theme=None)

with tab_src:
    st.subheader("Data sources, dates and fetch status")
    st.caption("ᛊ Sowilo (sun) = fetched live ᛫ ᚾ Naudiz (need) = live fetch failed, snapshot shown")

    def status(d):
        return "ᛊ Live" if d["live"] else "ᚾ Snapshot (live fetch failed)"

    src = pd.DataFrame([
        {"Data": f"Unlevered beta — {industry}", "Value": f"{fetched_beta:.4f}",
         "Data date": f"Updated {betas['date']}", "Source": BETAS_URL, "Status": status(betas),
         "Retrieved": betas["retrieved"]},
        {"Data": "USD BBB (Baa2) spread — large non-financial service firms", "Value": pct(spread_d["value"]),
         "Data date": f"Data as of {spread_d['date']}", "Source": RATINGS_URL, "Status": status(spread_d),
         "Retrieved": spread_d["retrieved"]},
        {"Data": "U.S. combined statutory corporate tax rate", "Value": f"{us_tax_tuple[0]:.2f}%",
         "Data date": f"Tax year {us_tax_tuple[1]}", "Source": OECD_API_URL, "Status": status(tax_d),
         "Retrieved": tax_d["retrieved"]},
        {"Data": f"{country} combined statutory corporate tax rate",
         "Value": f"{fc_tax_tuple[0]:.2f}%" if fc_tax_tuple else "n/a (manual input required)",
         "Data date": f"Tax year {fc_tax_tuple[1]}" if fc_tax_tuple else "—", "Source": OECD_API_URL,
         "Status": status(tax_d), "Retrieved": tax_d["retrieved"]},
        {"Data": "U.S. 10-year government bond yield", "Value": pct(y_us_d["value"], 3),
         "Data date": y_us_d["date"], "Source": y_us_d["url"], "Status": status(y_us_d),
         "Retrieved": y_us_d["retrieved"]},
        {"Data": f"{country} 10-year government bond yield", "Value": pct(y_fc_d["value"], 3),
         "Data date": y_fc_d["date"], "Source": y_fc_d["url"], "Status": status(y_fc_d),
         "Retrieved": y_fc_d["retrieved"]},
    ])
    st.dataframe(src, hide_index=True, width="stretch",
                 column_config={"Source": st.column_config.LinkColumn("Source")})
    st.markdown(
        f"- **Betas:** Aswath Damodaran, *Betas by Sector (US)* — [{BETAS_URL}]({BETAS_URL}), sheet "
        "“Industry Averages”, column “Unlevered beta”.\n"
        f"- **BBB spread:** Aswath Damodaran, *Ratings, Interest Coverage Ratios and Default Spread* — "
        f"[{RATINGS_URL}]({RATINGS_URL}), Baa2/BBB row of the large non-financial service firms table.\n"
        f"- **Tax rates:** OECD Corporate Tax Statistics database (dataflow DSD_TAX_CIT@DF_CIT, combined central + "
        f"sub-central statutory CIT rate, latest year available) — the same data as the "
        f"[OECD Corporate Tax Statistics report]({OECD_REPORT_URL}).\n"
        f"- **10Y yields:** Trading Economics — [{TE_BONDS_URL}]({TE_BONDS_URL}) (each country's "
        "“government-bond-yield” page).")
    errs = [(n, d["error"]) for n, d in [("Betas", betas), ("BBB spread", spread_d), ("OECD tax", tax_d),
                                         ("U.S. yield", y_us_d), (f"{country} yield", y_fc_d)] if d["error"]]
    if errs:
        with st.expander("Fetch error details"):
            for n, e in errs:
                st.code(f"{n}: {e}")

with tab_assump:
    st.subheader("Main assumptions")
    st.markdown(f"""
1. **Bottom-up beta.** The project uses the U.S. industry **unlevered beta** from Damodaran and relevers it at the
   target debt share with the Hamada formula: β_L = β_U × [1 + (1 − t) × D/E], where D/E = w_d / (1 − w_d).
2. **CAPM in USD.** k_e(USD) = y_US(10Y) + β_L × ERP. The ERP is a user input (default 6.5%) and is the same in both
   currencies.
3. **Cost of debt in USD.** k_d(USD) = y_US(10Y) + BBB spread, using Damodaran's Baa2/BBB default spread for large
   non-financial service firms.
4. **One project tax rate.** The same rate (U.S. or selected country, OECD combined statutory CIT rate) is used for
   relevering beta and for the debt tax shield in **both** currencies.
5. **Currency conversion.** Government-bond yield differences are treated as expected inflation / currency
   depreciation differences:
   - *Multiplicative (default):* (1 + k_FC) = (1 + k_USD) × (1 + y_FC) / (1 + y_US). The auto foreign BBB spread
     is then spread_USD × (1 + y_FC) / (1 + y_US).
   - *Additive:* k_FC = k_USD + (y_FC − y_US); the foreign BBB spread equals the USD spread.
   - If a manual foreign spread is entered, k_d(FC) = y_FC + manual spread.
6. **WACC** = (1 − w_d) × k_e + w_d × k_d × (1 − t), computed from each currency's own components.
7. **No separate country risk premium** is added; the local government yield is used as the local risk-free rate
   (for countries whose government bonds carry default risk, this embeds that risk).
8. **Data recency.** Betas and spreads are Damodaran's latest annual update; tax rates are the latest year in the OECD
   database; yields are the latest Trading Economics quote. Data is cached for 6 hours — press **Refresh data**
   to re-fetch.

*Rune key (decorative):* ᚠ fehu, wealth (USD) ᛫ ᚱ raidho, journey (foreign currency) ᛫ ᛗ mannaz, people
(all industries) ᛫ ᚨ ansuz, wisdom (sources) ᛫ ᛞ dagaz, daylight (assumptions) ᛫ ᛃ jera, the turning year (refresh)
᛫ ᛒ berkano, growth (downloads). The banner transliterates "cost of capital" into Elder Futhark.

> ⚠️ The course will provide its own formulas. Check them against items 1–6 above; every formula is in the
> function `compute_cost_of_capital()` in `app.py`, so any change is made in one place.
""")

# ----------------------------- Downloads -----------------------------------
rune_divider("ᛟ ᚠ ᛒ ᚠ ᛟ")
st.subheader("ᛒ Download results")
dl1, dl2, dl3 = st.columns(3)

summary_csv = ("INPUTS\n" + inputs_df.to_csv(index=False) + "\nRESULTS\n" + out_df.to_csv(index=False)).encode()
dl1.download_button("ᛒ Selected project (CSV)", summary_csv,
                    file_name=f"cost_of_capital_{country.replace(' ', '_')}.csv", mime="text/csv",
                    width="stretch")
dl2.download_button("ᛒ All industries (CSV)", all_df.to_csv(index=False).encode(),
                    file_name=f"all_industries_{country.replace(' ', '_')}.csv", mime="text/csv",
                    width="stretch")

xbuf = io.BytesIO()
with pd.ExcelWriter(xbuf, engine="openpyxl") as xw:
    inputs_df.to_excel(xw, sheet_name="Inputs", index=False)
    out_df.to_excel(xw, sheet_name="Results", index=False)
    all_df.to_excel(xw, sheet_name="All industries", index=False)
dl3.download_button("ᛒ Everything (Excel)", xbuf.getvalue(),
                    file_name=f"cost_of_capital_{country.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch")
