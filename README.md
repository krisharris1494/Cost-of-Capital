[README_2.md](https://github.com/user-attachments/files/34888583/README_2.md)
# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD** and in the
**currency of any selected country**, using live market and tax data.

## Features

- **Live data with sources and dates** (cached for 6 hours; a **🔄 Refresh data** button re-fetches everything)
  | Input | Source | What is used |
  |---|---|---|
  | Industry unlevered beta | [Damodaran – betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | Sheet "Industry Averages", column "Unlevered beta" |
  | USD BBB borrowing spread | [Damodaran – ratings.html](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html) | Baa2/BBB row, large non-financial service firms |
  | Corporate tax rates | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) via the OECD SDMX API (dataflow `DSD_TAX_CIT@DF_CIT`) | Combined (central + sub-central) statutory CIT rate, latest year available |
  | 10-year government bond yields | [Trading Economics – bonds](https://tradingeconomics.com/bonds) | Each country's `/government-bond-yield` page (no API key) |
- **Inputs:** industry, target country (the 54 countries listed on Trading Economics' bonds page), equity risk
  premium, target debt share, project tax rate (U.S. or selected country), and currency-conversion method.
- **Manual overrides** (toggles) for: unlevered beta, U.S. tax rate, foreign tax rate, USD BBB spread, U.S. and
  foreign 10Y yields, and the foreign-currency BBB spread (when switched off, the auto-calculated value is shown).
- **Side-by-side results** in USD and the foreign currency, a component table, an **all-industry comparison**
  (table + chart), an **assumptions** tab, and **downloads** (CSV and Excel).
- **Defaults on open:** Software (System & Application), United States, U.S. tax rate, 6.5% ERP, 30% debt.
- **Norse rune theme:** dark carved-stone look with ember-gold (USD) and frost-blue (foreign currency) accents,
  Elder Futhark rune labels, and Cinzel / Spectral / Noto Sans Runic fonts. Colors and fonts are set in
  `.streamlit/config.toml`; the decorative CSS is at the top of the UI section in `app.py`.
- **Snapshot fallback:** if a site blocks the request, the app uses a snapshot captured on 2026-11-15 and says so
  in a warning banner and in the *Data sources* tab.

## Formulas (all in `compute_cost_of_capital()` in `app.py`)

| Step | Formula |
|---|---|
| Debt-to-equity | D/E = w_d / (1 − w_d) |
| Levered beta (Hamada) | β_L = β_U × [1 + (1 − t) × D/E] |
| Cost of equity, USD | k_e = y_US + β_L × ERP |
| Cost of debt, USD | k_d = y_US + BBB spread |
| Foreign currency, multiplicative (default) | (1 + k_FC) = (1 + k_USD) × (1 + y_FC) / (1 + y_US) |
| Auto foreign BBB spread (multiplicative) | spread_FC = spread_USD × (1 + y_FC) / (1 + y_US) |
| Foreign currency, additive (option) | k_FC = k_USD + (y_FC − y_US); spread_FC = spread_USD |
| Manual foreign spread | k_d,FC = y_FC + manual spread |
| WACC (each currency) | (1 − w_d) × k_e + w_d × k_d × (1 − t) |

The same tax rate, debt share and ERP are used in both currencies. **Check these against the formulas given in
class** and edit `compute_cost_of_capital()` if they differ.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `requirements.txt`, `README.md` and the theme file
   `.streamlit/config.toml` (on GitHub: **Add file → Create new file**, type `.streamlit/config.toml` as the
   name, and paste the contents).
2. Go to [share.streamlit.io](https://share.streamlit.io), click **Create app**, pick the repository and branch,
   and set the main file to `app.py`.
3. Click **Deploy**.

## Notes and limitations

- Trading Economics has bot protection. If it blocks the cloud server, the app shows the labelled snapshot yields;
  enter current yields with the manual override if needed.
- The OECD database has no rate for Russia or Taiwan; the app asks for a manual tax rate for those countries.
- Damodaran's betas are for U.S. companies and are updated once a year (in January).
