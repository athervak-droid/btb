"""SEC EDGAR data tools (free, public, no API key).

Implements the two data tools the harness exposes to the agent:

  - edgar_search(ticker_or_cik, form_type=None, as_of=None)
        Resolve a ticker (or raw CIK) to a CIK, then return matching filings
        (form, date, accession, and a direct URL to the primary document) from
        SEC EDGAR's submissions API.

  - market_data(ticker, field, as_of=None)
        Return fundamentals for a US public company from EDGAR's XBRL
        company-facts API. EDGAR is filings only: it has reported financial
        line items, NOT market prices or sell-side consensus. Those fields
        return a clear, honest error so a caller knows to wire a price/estimates
        vendor (we deliberately do not bundle licensed market data).

Standard library only (urllib) so it runs without `pip install` and adds no
dependency to the project. SEC asks every automated client to send a
descriptive User-Agent with a contact email; set SEC_USER_AGENT to override the
default. See https://www.sec.gov/os/webmaster-faq#developers and
https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error

# SEC requires a UA identifying the caller + a contact. Override via env.
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "banker-tool-bench/0.1 (research benchmark; contact: set SEC_USER_AGENT)",
)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/{taxonomy}/{tag}.json"

_TICKER_CACHE: dict | None = None  # ticker (upper) -> {cik_str, ticker, title}


# ----------------------------- HTTP -----------------------------

def _get_json(url: str, retries: int = 3, backoff: float = 1.0):
    """GET a URL and parse JSON, with the SEC-required UA and light retry.

    SEC throttles to ~10 req/s and 403s requests without a real UA. We surface a
    readable error rather than a raw traceback so the agent/tool layer can react.
    """
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} for {url}"
            if e.code in (403, 429, 500, 502, 503):
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(last_err) from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = f"network error for {url}: {e}"
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(last_err or f"failed to GET {url}")


# ----------------------------- CIK resolution -----------------------------

def _load_ticker_map() -> dict:
    global _TICKER_CACHE
    if _TICKER_CACHE is None:
        data = _get_json(_TICKER_MAP_URL)
        # file is {"0": {"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...}
        _TICKER_CACHE = {row["ticker"].upper(): row for row in data.values()}
    return _TICKER_CACHE


def resolve_cik(ticker_or_cik: str) -> str:
    """Return a 10-digit zero-padded CIK string for a ticker or raw CIK."""
    s = str(ticker_or_cik).strip()
    if s.upper().startswith("CIK"):
        s = s[3:]
    if s.isdigit():
        return s.zfill(10)
    row = _load_ticker_map().get(s.upper())
    if not row:
        raise RuntimeError(f"no CIK found for ticker {ticker_or_cik!r} in SEC ticker map")
    return str(row["cik_str"]).zfill(10)


# ----------------------------- edgar_search -----------------------------

def edgar_search(ticker_or_cik: str, form_type: str | None = None,
                 as_of: str | None = None, limit: int = 10, **_) -> dict:
    """Search SEC filings for a company.

    Returns {company, cik, filings: [{form, filing_date, accession, primary_doc,
    url, description}]}, most recent first, filtered to form_type (exact or
    prefix, case-insensitive) and to filings on/before as_of (YYYY-MM-DD).
    """
    cik10 = resolve_cik(ticker_or_cik)
    data = _get_json(_SUBMISSIONS_URL.format(cik10=cik10))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [])
    cik_int = int(cik10)

    ft = (form_type or "").upper().strip()
    out = []
    for i in range(len(forms)):
        form = forms[i]
        date = dates[i]
        if ft and not (form.upper() == ft or form.upper().startswith(ft)):
            continue
        if as_of and date > as_of:
            continue
        accn_nodash = accns[i].replace("-", "")
        primary = docs[i] if i < len(docs) else ""
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
               f"{accn_nodash}/{primary}") if primary else (
               f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&CIK={cik10}&type={ft}")
        out.append({
            "form": form,
            "filing_date": date,
            "accession": accns[i],
            "primary_doc": primary,
            "description": descs[i] if i < len(descs) else "",
            "url": url,
        })
        if len(out) >= limit:
            break
    return {
        "company": data.get("name"),
        "cik": cik10,
        "ticker": (data.get("tickers") or [None])[0],
        "matched": len(out),
        "filings": out,
    }


# ----------------------------- market_data (fundamentals) -----------------------------

# Logical field -> ordered list of (taxonomy, XBRL tag) candidates to try.
# EBITDA and net debt are not single GAAP tags; we compute them from components.
_FIELD_TAGS = {
    "revenue": [("us-gaap", "Revenues"),
                ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")],
    "net_income": [("us-gaap", "NetIncomeLoss")],
    "operating_income": [("us-gaap", "OperatingIncomeLoss")],
    "d_and_a": [("us-gaap", "DepreciationDepletionAndAmortization"),
                ("us-gaap", "DepreciationAmortizationAndAccretionNet"),
                ("us-gaap", "DepreciationAndAmortization")],
    "interest_expense": [("us-gaap", "InterestExpense"),
                         ("us-gaap", "InterestExpenseNonoperating")],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
             ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")],
    "long_term_debt_noncurrent": [("us-gaap", "LongTermDebtNoncurrent"),
                                  ("us-gaap", "LongTermDebt")],
    "long_term_debt_current": [("us-gaap", "LongTermDebtCurrent"),
                               ("us-gaap", "DebtCurrent")],
    # Include LP-unit tags: many midstream names are MLPs that report partnership
    # units rather than common shares.
    "shares_diluted": [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
                       ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstandingCommon"),
                       ("us-gaap", "WeightedAverageLimitedPartnershipUnitsOutstandingDiluted"),
                       ("us-gaap", "WeightedAverageNumberOfLimitedPartnershipAndGeneralPartnershipUnitOutstandingDiluted")],
    "shares_basic": [("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
                     ("us-gaap", "WeightedAverageNumberOfSharesOutstanding"),
                     ("us-gaap", "WeightedAverageLimitedPartnershipUnitsOutstanding")],
    "assets": [("us-gaap", "Assets")],
    "equity": [("us-gaap", "StockholdersEquity")],
}

# Market prices: not in EDGAR. Served from a price vendor (Tiingo) when
# TIINGO_API_KEY is set; otherwise these raise with a clear message.
_PRICE_FIELDS = {"close_price", "price", "share_price", "close"}
_PRICE_DERIVED = {"market_cap", "enterprise_value"}  # price x shares (+ net debt)

# Sell-side consensus / estimates: licensed, no free source. Always raise; state
# these in the task prompt instead (the benchmark allows prompt-stated inputs).
_CONSENSUS_FIELDS = {
    "consensus", "consensus_estimate", "estimate", "ltm_ebitda_consensus",
    "distributable_cash_flow_consensus", "target_price", "forward_eps", "forward_ebitda",
}

# Derived fields computed from EDGAR component facts.
_DERIVED = {"net_debt", "ebitda", "total_debt", "net_debt_to_ebitda", "interest_coverage"}

TIINGO_API_KEY = os.environ.get("TIINGO_API_KEY", "")
_TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}&endDate={end}&token={token}"


def _tiingo_close(ticker: str, as_of: str | None):
    """Most recent daily close on/before as_of (YYYY-MM-DD) from Tiingo (free
    tier, needs TIINGO_API_KEY). Returns (close, date) or raises."""
    if not TIINGO_API_KEY:
        raise RuntimeError(
            "price data needs a vendor: set TIINGO_API_KEY (free tier at "
            "tiingo.com) so market_data can return prices. EDGAR has filings only.")
    end = as_of or "2100-01-01"
    # look back ~2 weeks before as_of to span weekends/holidays; if no as_of, the
    # vendor returns the full series and we take the last row.
    start = "1990-01-01"
    if as_of:
        y, m, d = (int(x) for x in as_of.split("-"))
        start = f"{y:04d}-{max(1, m-1):02d}-01"
    url = _TIINGO_URL.format(ticker=ticker.lower(), start=start, end=end, token=TIINGO_API_KEY)
    rows = _get_json(url)
    rows = [r for r in rows if r.get("close") is not None]
    if not rows:
        raise RuntimeError(f"no Tiingo price for {ticker!r} on/before {as_of}")
    rows.sort(key=lambda r: r["date"])
    last = rows[-1]
    return last["close"], last["date"][:10]


def _concept_series(cik10: str, taxonomy: str, tag: str):
    """Return the list of fact dicts for one XBRL concept, or None if absent."""
    url = _CONCEPT_URL.format(cik10=cik10, taxonomy=taxonomy, tag=tag)
    try:
        data = _get_json(url)
    except RuntimeError:
        return None
    units = data.get("units", {})
    # prefer USD, then shares, then whatever single unit exists
    for key in ("USD", "shares", "USD/shares"):
        if key in units:
            return units[key]
    return next(iter(units.values()), None)


def _pick_value(series, as_of: str | None, prefer_annual: bool = True):
    """Pick the most recent fact at/before as_of. Prefer full-year (FY) facts
    for flow items so we don't return a single quarter by accident."""
    if not series:
        return None
    rows = [r for r in series if r.get("end") and (not as_of or r["end"] <= as_of)]
    if not rows:
        rows = list(series)
    if prefer_annual:
        annual = [r for r in rows if r.get("fp") == "FY" or (
            r.get("start") and r.get("end") and
            (int(r["end"][:4]) - int(r["start"][:4])) >= 1)]
        if annual:
            rows = annual
    rows.sort(key=lambda r: (r.get("end", ""), r.get("filed", "")))
    return rows[-1]


def _logical(cik10: str, field: str, as_of: str | None):
    """Fetch a logical field. Tries every candidate tag and keeps the one with
    the most recent fact, so a deprecated tag (e.g. ONEOK's old `Revenues`,
    which stops in 2022) doesn't shadow the current one."""
    point_in_time = field in ("cash", "long_term_debt_noncurrent",
                              "long_term_debt_current", "assets", "equity")
    best = None  # (fact, tag, taxonomy)
    for taxonomy, tag in _FIELD_TAGS.get(field, []):
        series = _concept_series(cik10, taxonomy, tag)
        fact = _pick_value(series, as_of, prefer_annual=not point_in_time)
        if fact is None:
            continue
        if best is None or fact.get("end", "") > best[0].get("end", ""):
            best = (fact, tag, taxonomy)
    if best is None:
        return None, None
    fact, tag, taxonomy = best
    return fact.get("val"), {**fact, "tag": tag, "taxonomy": taxonomy}


def market_data(ticker: str, field: str, as_of: str | None = None, **_) -> dict:
    """Return one field for a company: EDGAR fundamentals, or a market price via
    Tiingo (when TIINGO_API_KEY is set). Sell-side consensus has no free source
    and raises - state those in the task prompt.
    """
    f = field.strip().lower()

    if f in _CONSENSUS_FIELDS:
        raise RuntimeError(
            f"field {field!r} is sell-side consensus/estimate, which has no free "
            f"source. State it in the task prompt as a given assumption.")

    if f in _PRICE_FIELDS:
        close, date = _tiingo_close(ticker, as_of)
        return {"ticker": ticker.upper(), "field": f, "value": close,
                "as_of": date, "unit": "USD/share",
                "source": {"vendor": "tiingo", "type": "daily_close"}}

    if f in _PRICE_DERIVED:
        close, date = _tiingo_close(ticker, as_of)
        cik10 = resolve_cik(ticker)
        shares, _sf = _logical(cik10, "shares_diluted", as_of)
        if not shares:
            raise RuntimeError(f"need diluted shares for {f!r}; no XBRL fact found")
        market_cap = close * shares
        if f == "market_cap":
            value = market_cap
        else:  # enterprise_value = market cap + net debt
            nd = _derived(cik10, ticker, "net_debt", as_of)["value"]
            value = market_cap + (nd or 0)
        return {"ticker": ticker.upper(), "field": f, "value": value, "as_of": date,
                "unit": "USD", "note": "market_cap = close x diluted shares"
                + ("; EV = market_cap + net_debt" if f == "enterprise_value" else ""),
                "source": {"price_vendor": "tiingo", "shares": "EDGAR XBRL"}}

    cik10 = resolve_cik(ticker)

    if f in _FIELD_TAGS:
        val, fact = _logical(cik10, f, as_of)
        if val is None:
            raise RuntimeError(f"no XBRL fact found for field {field!r} (cik {cik10})")
        return {"ticker": ticker.upper(), "field": f, "value": val,
                "as_of": fact.get("end"), "unit": "USD" if f not in
                ("shares_diluted", "shares_basic") else "shares",
                "source": {"form": fact.get("form"), "accession": fact.get("accn"),
                           "fiscal": f"{fact.get('fy')}{fact.get('fp')}",
                           "tag": fact.get("tag")}}

    if f in _DERIVED:
        return _derived(cik10, ticker, f, as_of)

    raise RuntimeError(
        f"unknown field {field!r}. Known fundamentals: {sorted(_FIELD_TAGS)}; "
        f"derived: {sorted(_DERIVED)}.")


def _derived(cik10: str, ticker: str, field: str, as_of: str | None) -> dict:
    """Compute net_debt / total_debt / ebitda / ratios from component facts."""
    def get(name):
        v, fact = _logical(cik10, name, as_of)
        return v, fact

    if field in ("net_debt", "total_debt", "net_debt_to_ebitda", "interest_coverage", "ebitda"):
        ltd, ltd_f = get("long_term_debt_noncurrent")
        cur, cur_f = get("long_term_debt_current")
        cash, cash_f = get("cash")
        oi, oi_f = get("operating_income")
        da, da_f = get("d_and_a")
        ie, ie_f = get("interest_expense")

        total_debt = (ltd or 0) + (cur or 0)
        net_debt = total_debt - (cash or 0)
        ebitda = (oi or 0) + (da or 0)

        srcs = {k: ({"tag": fct.get("tag"), "accession": fct.get("accn"),
                     "end": fct.get("end")} if fct else None)
                for k, fct in [("long_term_debt_noncurrent", ltd_f),
                               ("long_term_debt_current", cur_f), ("cash", cash_f),
                               ("operating_income", oi_f), ("d_and_a", da_f),
                               ("interest_expense", ie_f)]}

        if field == "total_debt":
            value = total_debt
        elif field == "net_debt":
            value = net_debt
        elif field == "ebitda":
            value = ebitda
        elif field == "net_debt_to_ebitda":
            value = (net_debt / ebitda) if ebitda else None
        else:  # interest_coverage = EBITDA / interest expense
            value = (ebitda / ie) if ie else None

        return {"ticker": ticker.upper(), "field": field, "value": value,
                "as_of": as_of,
                "note": ("EBITDA approximated as OperatingIncomeLoss + D&A; EBITDA "
                         "is non-GAAP and not a tagged XBRL concept. Verify against "
                         "the filing's reconciliation." if "ebitda" in field or
                         field in ("net_debt_to_ebitda", "interest_coverage") else
                         "net_debt = long-term debt (incl. current) - cash & equivalents."),
                "components": srcs}

    raise RuntimeError(f"unhandled derived field {field!r}")


# ----------------------------- smoke test -----------------------------

if __name__ == "__main__":
    # Free, live smoke test against SEC EDGAR. Set SEC_USER_AGENT to a real
    # contact first (SEC 403s clients without one):
    #   SEC_USER_AGENT="you (you@example.com)" python harness/tools_edgar.py [TICKER]
    import sys
    tkr = sys.argv[1] if len(sys.argv) > 1 else "OKE"
    if "set SEC_USER_AGENT" in USER_AGENT:
        print("WARNING: set SEC_USER_AGENT to a real contact or SEC may return 403.\n")
    s = edgar_search(tkr, form_type="10-K", limit=2)
    print(f"{s['company']} (CIK {s['cik']}) - latest 10-Ks:")
    for fl in s["filings"]:
        print(f"  {fl['filing_date']}  {fl['url']}")
    print("\nFundamentals:")
    for fld in ("revenue", "net_income", "shares_diluted", "net_debt", "ebitda",
                "net_debt_to_ebitda", "interest_coverage"):
        try:
            d = market_data(tkr, fld)
            print(f"  {fld:20s} = {d['value']:,.2f}" if isinstance(d["value"], (int, float))
                  else f"  {fld:20s} = {d['value']}")
        except Exception as e:
            print(f"  {fld:20s} ERROR: {e}")
