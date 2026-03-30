#!/usr/bin/env python3
"""
AI-DOC Observatory — Unified Pipeline
=======================================
Single script that:
1. Reads your author ID list (Excel with name, author_id, status columns)
2. Fetches papers from Semantic Scholar API (2024+)
3. Looks up venue rankings from SCImago CSV, JUFO CSV, and Google Scholar CSV
4. Saves a history snapshot to ai_doc_history.json
5. Exports papers_with_rankings.xlsx
6. Bakes the self-contained observatory HTML

Usage:
    python run_observatory.py authors.xlsx \\
        --scimago "scimagojr 2024.csv" \\
        --jufo jufo_channels.csv \\
        --gs google_scholar_metrics.csv \\
        --template observatory_public.html

All flags except the author Excel are optional (rankings will be empty if CSVs not provided).

Requirements:
    pip install requests pandas
"""

import sys, json, re, csv, time, zipfile, os
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from collections import Counter
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("ERROR: pip install requests"); sys.exit(1)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════
HISTORY_FILE = "ai_doc_history.json"
SS_API = "https://api.semanticscholar.org/graph/v1"
MIN_YEAR = 2023
API_DELAY = 30.0  # seconds between SS API calls


# ═══════════════════════════════════════════════════════
# Excel reader (handles NaN strings that break openpyxl)
# ═══════════════════════════════════════════════════════
def read_xlsx(path):
    if HAS_PANDAS:
        try:
            df = pd.read_excel(path)
            df = df.fillna("")
            return df.to_dict("records")
        except Exception:
            pass
    # Fallback: manual XML parse
    with zipfile.ZipFile(path) as z:
        ss = []
        if 'xl/sharedStrings.xml' in z.namelist():
            tree = ET.parse(z.open('xl/sharedStrings.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in tree.findall('.//s:si', ns):
                ss.append(''.join(t.text or '' for t in si.findall('.//s:t', ns)))
        tree = ET.parse(z.open('xl/worksheets/sheet1.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        raw_rows = []
        for row_el in tree.findall('.//s:sheetData/s:row', ns):
            row = {}
            for cell in row_el.findall('s:c', ns):
                ref = cell.get('r'); col = re.match(r'([A-Z]+)', ref).group(1)
                t = cell.get('t', ''); v_el = cell.find('s:v', ns)
                val = v_el.text if v_el is not None else ''
                if t == 's' and val.isdigit(): val = ss[int(val)]
                elif val in ('NaN', 'nan', 'None', 'none'): val = ''
                row[col] = val
            raw_rows.append(row)
    headers = raw_rows[0]; cols = sorted(headers.keys(), key=lambda c: (len(c), c))
    hnames = [headers[c] for c in cols]
    data = []
    for raw in raw_rows[1:]:
        d = {}
        for c, h in zip(cols, hnames):
            v = raw.get(c, '') or ''
            if h in ('year', 'jufo_level', 'gs_h5_index', 'gs_h5_median'):
                try: v = int(float(v)) if v else ''
                except: v = ''
            elif h == 'scimago_sjr':
                try: v = round(float(v), 3) if v else ''
                except: v = ''
            d[h] = v
        data.append(d)
    return data


# ═══════════════════════════════════════════════════════
# CSV index builders
# ═══════════════════════════════════════════════════════
def build_scimago_index(csv_path):
    idx = {"byIssn": {}, "byName": {}}
    with open(csv_path, encoding="utf-8") as f:
        text = f.read()
    sep = "\t" if "\t" in text.split("\n")[0] else ";"
    lines = text.split("\n")
    headers = [h.strip().lower().strip('"') for h in lines[0].split(sep)]
    for line in lines[1:]:
        if not line.strip(): continue
        vals = [v.strip().strip('"') for v in line.split(sep)]
        row = dict(zip(headers, vals))
        for issn in (row.get("issn", "") or "").split(","):
            c = issn.strip().replace("-", "")
            if len(c) >= 7: idx["byIssn"][c] = row
        t = (row.get("title", "") or "").lower().strip()
        if t: idx["byName"][t] = row
    return idx


def build_jufo_index(csv_path):
    idx = {"byIssn": {}, "byName": {}}
    with open(csv_path, encoding="utf-8") as f:
        text = f.read()
    fl = text.split("\n")[0]
    sep = "\t" if fl.count("\t") > fl.count(";") else (";" if fl.count(";") > fl.count(",") else ",")
    lines = text.split("\n")
    headers = [h.strip().lower().strip('"') for h in lines[0].split(sep)]
    for line in lines[1:]:
        if not line.strip(): continue
        vals = [v.strip().strip('"') for v in line.split(sep)]
        row = dict(zip(headers, vals))
        for h in headers:
            if "issn" in h:
                for issn in re.split(r'[,;\s]+', row.get(h, "")):
                    c = issn.strip().replace("-", "")
                    if len(c) >= 7: idx["byIssn"][c] = row
            if re.search(r'name|title|nimi', h):
                n = (row.get(h, "") or "").lower().strip()
                if n and n != "nan": idx["byName"][n] = row
    return idx


def build_gs_index(csv_path):
    idx = {"byName": {}}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("venue_name", "") or "").lower().strip()
            if name: idx["byName"][name] = r
    return idx


def build_jcr_index(csv_path):
    """Build index from JCR (Clarivate) CSV export. Tab-separated with headers:
    Name, Web of Science Documents, Times Cited, Rank, % Docs Cited,
    Journal Impact Factor, JIF Quartile, ISSN, eISSN"""
    idx = {"byIssn": {}, "byName": {}}
    with open(csv_path, encoding="utf-8") as f:
        text = f.read()
    sep = "\t" if "\t" in text.split("\n")[0] else ","
    lines = text.split("\n")
    headers = [h.strip().lower().strip('"') for h in lines[0].split(sep)]
    for line in lines[1:]:
        if not line.strip(): continue
        vals = [v.strip().strip('"') for v in line.split(sep)]
        row = dict(zip(headers, vals))
        # Index by ISSN and eISSN
        for col in ("issn", "eissn"):
            issn_val = row.get(col, "")
            if issn_val:
                c = issn_val.strip().replace("-", "")
                if len(c) >= 7: idx["byIssn"][c] = row
        # Index by name
        name = (row.get("name", "") or "").lower().strip()
        if name: idx["byName"][name] = row
    return idx


# ═══════════════════════════════════════════════════════
# Venue lookups
# ═══════════════════════════════════════════════════════
def lookup_scimago(idx, venue, issn):
    if not idx: return {"quartile": None, "sjr": None}
    row = None
    if issn:
        row = idx["byIssn"].get(issn.replace("-", "").strip())
    if not row and venue:
        row = idx["byName"].get(venue.lower().strip())
    if row:
        sjr = None
        for k in ("sjr", "sjr indicator"):
            if row.get(k):
                try: sjr = float(str(row[k]).replace(",", ".")); break
                except: pass
        q = None
        for k in ("sjr best quartile", "best quartile", "quartile"):
            if row.get(k): q = row[k].strip(); break
        return {"quartile": q, "sjr": sjr}
    return {"quartile": None, "sjr": None}


def lookup_jufo(idx, venue, issn):
    if not idx: return {"level": None}
    row = None
    if issn:
        row = idx["byIssn"].get(issn.replace("-", "").strip())
    if not row and venue:
        row = idx["byName"].get(venue.lower().strip())
    if row:
        for k in row:
            if re.search(r'level|taso|luokka', k, re.I):
                v = row[k]
                if v and v.strip() and v.strip().lower() not in ('nan', 'none', ''):
                    try:
                        level = int(float(v))
                        if level in (0, 1, 2, 3):
                            return {"level": level}
                    except: pass
                # Venue was found in JUFO but level is empty/NaN → that means level 0
                return {"level": 0}
    return {"level": None}


def lookup_gs(idx, venue):
    if not idx or not venue: return {"h5_index": None, "h5_median": None}
    vl = venue.lower().strip()
    row = idx["byName"].get(vl)
    if not row:
        for key, val in idx["byName"].items():
            if key in vl or vl in key:
                row = val; break
    if row:
        h5 = None; med = None
        try: h5 = int(row["h5_index"])
        except: pass
        try: med = int(row["h5_median"])
        except: pass
        return {"h5_index": h5, "h5_median": med}
    return {"h5_index": None, "h5_median": None}


def lookup_jcr(idx, venue, issn):
    """Look up Journal Impact Factor and JIF Quartile from JCR data."""
    if not idx: return {"jif": None, "jif_quartile": None}
    row = None
    if issn:
        row = idx["byIssn"].get(issn.replace("-", "").strip())
    if not row and venue:
        row = idx["byName"].get(venue.lower().strip())
    if row:
        jif = None; jif_q = None
        jif_val = row.get("journal impact factor", "")
        if jif_val and jif_val.strip().lower() not in ("", "n/a", "nan", "not available"):
            try: jif = round(float(jif_val.replace(",", ".")), 1)
            except: pass
        jif_q_val = row.get("jif quartile", "")
        if jif_q_val and jif_q_val.strip() in ("Q1", "Q2", "Q3", "Q4"):
            jif_q = jif_q_val.strip()
        return {"jif": jif, "jif_quartile": jif_q}
    return {"jif": None, "jif_quartile": None}


# ═══════════════════════════════════════════════════════
# Semantic Scholar API
# ═══════════════════════════════════════════════════════
def ss_get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"    ⏳ Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                print(f"    ⚠ HTTP {resp.status_code}")
                return None
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"    ⚠ Error: {e}")
    return None


def fetch_author_papers(author_id, min_year):
    data = ss_get(f"{SS_API}/author/{author_id}/papers",
                  {"fields": "title,year,publicationDate,venue,externalIds,publicationVenue", "limit": "500"})
    if not data: return []
    papers = []
    for p in data.get("data", []):
        year = p.get("year")
        if year is None and p.get("publicationDate"):
            m = re.match(r"(\d{4})", str(p["publicationDate"]))
            if m: year = int(m.group(1))
        if year is not None and year >= min_year:
            papers.append({**p, "_year": year})
    return papers


# ═══════════════════════════════════════════════════════
# History snapshot
# ═══════════════════════════════════════════════════════
def build_snapshot(papers, snapshot_date=None):
    if not snapshot_date: snapshot_date = date.today().isoformat()
    authors = set(p.get("author_name", "") for p in papers if p.get("author_name"))
    qc = Counter(); jc = Counter()
    for p in papers:
        q = p.get("scimago_quartile", "")
        qc[q if q in ("Q1", "Q2", "Q3", "Q4") else "N/A"] += 1
        j = str(p.get("jufo_level", ""))
        jc[j if j in ("0", "1", "2", "3") else "N/A"] += 1
    h5 = {"200+": 0, "100-199": 0, "50-99": 0, "1-49": 0, "N/A": 0}
    for p in papers:
        v = p.get("gs_h5_index", "")
        if v == "" or v is None: h5["N/A"] += 1
        elif int(v) >= 200: h5["200+"] += 1
        elif int(v) >= 100: h5["100-199"] += 1
        elif int(v) >= 50: h5["50-99"] += 1
        else: h5["1-49"] += 1
    sjrs = [float(p["scimago_sjr"]) for p in papers if p.get("scimago_sjr") and str(p["scimago_sjr"]) not in ("", "nan", "NaN")]
    avg_sjr = round(sum(sjrs) / len(sjrs), 2) if sjrs else None
    s = sorted(sjrs); m = len(s) // 2
    med_sjr = round(s[m] if len(s) % 2 else (s[m-1] + s[m]) / 2, 2) if sjrs else None
    # JIF stats
    jifq = Counter()
    for p in papers:
        jq = p.get("jif_quartile", "")
        jifq[jq if jq in ("Q1", "Q2", "Q3", "Q4") else "N/A"] += 1
    jifs = [float(p["jif"]) for p in papers if p.get("jif") and str(p["jif"]) not in ("", "nan", "NaN")]
    avg_jif = round(sum(jifs) / len(jifs), 2) if jifs else None
    return {
        "date": snapshot_date, "total": len(papers), "authors": len(authors),
        "q1": qc.get("Q1", 0), "q2": qc.get("Q2", 0), "q3": qc.get("Q3", 0), "q4": qc.get("Q4", 0), "q_na": qc.get("N/A", 0),
        "jufo3": jc.get("3", 0), "jufo2": jc.get("2", 0), "jufo1": jc.get("1", 0), "jufo0": jc.get("0", 0), "jufo_na": jc.get("N/A", 0),
        "h5_200plus": h5["200+"], "h5_100_199": h5["100-199"], "h5_50_99": h5["50-99"], "h5_1_49": h5["1-49"], "h5_na": h5["N/A"],
        "jif_q1": jifq.get("Q1", 0), "jif_q2": jifq.get("Q2", 0), "jif_q3": jifq.get("Q3", 0), "jif_q4": jifq.get("Q4", 0), "jif_na": jifq.get("N/A", 0),
        "avg_sjr": avg_sjr, "med_sjr": med_sjr, "avg_jif": avg_jif,
    }


# ═══════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════
def run(author_xlsx, scimago_csv=None, jufo_csv=None, gs_csv=None, jcr_csv=None,
        template_path=None, output_path=None, history_path=None, min_year=MIN_YEAR):

    if not history_path: history_path = HISTORY_FILE
    today = date.today().isoformat()

    # ─── 1. Load authors ───
    print(f"[1/6] Loading authors from {author_xlsx}...")
    rows = read_xlsx(author_xlsx)
    authors = []
    for r in rows:
        aid = str(r.get("author_id", "")).replace(".0", "").strip()
        status = str(r.get("status", "")).upper()
        name = r.get("name", "")
        if aid and status == "CONFIRMED":
            authors.append({"name": name, "author_id": aid})
    print(f"  {len(authors)} CONFIRMED authors")

    # ─── 2. Load ranking CSVs ───
    print(f"[2/6] Loading ranking datasets...")
    sci_idx = build_scimago_index(scimago_csv) if scimago_csv else None
    jufo_idx = build_jufo_index(jufo_csv) if jufo_csv else None
    gs_idx = build_gs_index(gs_csv) if gs_csv else None
    jcr_idx = build_jcr_index(jcr_csv) if jcr_csv else None
    if sci_idx: print(f"  SCImago: {len(sci_idx['byIssn'])} ISSNs, {len(sci_idx['byName'])} names")
    else: print("  SCImago: not loaded")
    if jufo_idx: print(f"  JUFO: {len(jufo_idx['byIssn'])} ISSNs, {len(jufo_idx['byName'])} names")
    else: print("  JUFO: not loaded")
    if gs_idx: print(f"  GS: {len(gs_idx['byName'])} venues")
    else: print("  GS: not loaded")
    if jcr_idx: print(f"  JCR: {len(jcr_idx['byIssn'])} ISSNs, {len(jcr_idx['byName'])} names")
    else: print("  JCR (Impact Factor): not loaded")

    # ─── 3. Fetch papers from Semantic Scholar ───
    print(f"[3/6] Fetching papers from Semantic Scholar (min year {min_year})...")
    all_papers = []
    venue_cache = {}

    for i, a in enumerate(authors):
        print(f"  [{i+1}/{len(authors)}] {a['name']} ({a['author_id']})...", end=" ", flush=True)
        papers = fetch_author_papers(a["author_id"], min_year)
        print(f"{len(papers)} paper(s)")

        for p in papers:
            pv = p.get("publicationVenue") or {}
            vn = pv.get("name") or p.get("venue") or ""
            vi = None
            issns = pv.get("issn") or pv.get("alternate_issns")
            if isinstance(issns, list) and issns: vi = issns[0]
            elif isinstance(issns, str): vi = issns

            ck = vi or vn
            if ck and ck not in venue_cache:
                sci = lookup_scimago(sci_idx, vn, vi)
                jufo = lookup_jufo(jufo_idx, vn, vi)
                gs = lookup_gs(gs_idx, vn)
                jcr = lookup_jcr(jcr_idx, vn, vi)
                venue_cache[ck] = {**sci, **jufo, **gs, **jcr}
            vc = venue_cache.get(ck, {})
            ext = p.get("externalIds") or {}

            all_papers.append({
                "author_name": a["name"], "author_id": a["author_id"],
                "title": p.get("title", ""), "year": p["_year"],
                "publicationDate": p.get("publicationDate", ""),
                "venue": vn, "venue_issn": vi or "", "doi": ext.get("DOI", ""),
                "scimago_quartile": vc.get("quartile") or "",
                "scimago_sjr": vc.get("sjr") if vc.get("sjr") is not None else "",
                "jufo_level": vc.get("level") if vc.get("level") is not None else "",
                "gs_h5_index": vc.get("h5_index") if vc.get("h5_index") is not None else "",
                "gs_h5_median": vc.get("h5_median") if vc.get("h5_median") is not None else "",
                "jif": vc.get("jif") if vc.get("jif") is not None else "",
                "jif_quartile": vc.get("jif_quartile") or "",
                "paper_id": p.get("paperId", ""),
            })

        time.sleep(API_DELAY)

    print(f"\n  Total: {len(all_papers)} papers")
    sci_matched = sum(1 for p in all_papers if p["scimago_quartile"])
    jufo_matched = sum(1 for p in all_papers if p["jufo_level"] != "")
    gs_matched = sum(1 for p in all_papers if p["gs_h5_index"] != "")
    jcr_matched = sum(1 for p in all_papers if p["jif_quartile"])
    print(f"  SCImago matched: {sci_matched}, JUFO matched: {jufo_matched}, GS matched: {gs_matched}, JCR matched: {jcr_matched}")

    # ─── 4. Save Excel ───
    print(f"[4/6] Saving papers_with_rankings_{today}.xlsx...")
    excel_path = f"papers_with_rankings_{today}.xlsx"
    if HAS_PANDAS:
        df = pd.DataFrame(all_papers)
        cols = ["author_name","author_id","title","year","publicationDate","venue","venue_issn","doi",
                "scimago_quartile","scimago_sjr","jufo_level","gs_h5_index","gs_h5_median","jif","jif_quartile","paper_id"]
        df = df[[c for c in cols if c in df.columns]]
        df.to_excel(excel_path, index=False)
    else:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        cols = list(all_papers[0].keys()) if all_papers else []
        ws.append(cols)
        for p in all_papers:
            ws.append([p.get(c, "") for c in cols])
        wb.save(excel_path)
    print(f"  Saved {excel_path}")

    # ─── 5. Update history ───
    print(f"[5/6] Updating history ({history_path})...")
    hp = Path(history_path)
    history = json.loads(hp.read_text()) if hp.exists() else []
    snap = build_snapshot(all_papers, today)
    history = [h for h in history if h["date"] != today]
    history.append(snap)
    history.sort(key=lambda h: h["date"])
    hp.write_text(json.dumps(history, indent=2))
    print(f"  {len(history)} snapshot(s). Today: {snap['total']} papers, Q1={snap['q1']}, JUFO3={snap['jufo3']}")

    # ─── 6. Bake HTML ───
    if template_path is None:
        for c in [Path("observatory_aquarium.html"), Path("observatory_public.html"),
                  Path(__file__).parent / "observatory_aquarium.html",
                  Path(__file__).parent / "observatory_public.html"]:
            if c.exists(): template_path = str(c); break
    if not template_path:
        print("[6/6] ⚠ No template found — skipping HTML bake. Provide --template path.")
        return

    print(f"[6/6] Baking HTML from {template_path}...")
    html = Path(template_path).read_text(encoding="utf-8")

    # Inject logo if placeholder exists and logo file is found
    if "/*LOGO_BASE64*/" in html:
        logo_injected = False
        for logo_path in [Path("ai-doc-no-text.png"), Path(__file__).parent / "ai-doc-no-text.png"]:
            if logo_path.exists():
                try:
                    import base64
                    from PIL import Image
                    import io
                    img = Image.open(logo_path)
                    img.thumbnail((300, 120), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG', optimize=True)
                    logo_b64 = base64.b64encode(buf.getvalue()).decode()
                    html = html.replace("/*LOGO_BASE64*/", logo_b64)
                    print(f"  Logo injected from {logo_path} ({len(logo_b64)//1024}KB)")
                    logo_injected = True
                except ImportError:
                    # No PIL — try raw base64 without resize
                    import base64
                    logo_b64 = base64.b64encode(logo_path.read_bytes()).decode()
                    html = html.replace("/*LOGO_BASE64*/", logo_b64)
                    print(f"  Logo injected (no resize, {len(logo_b64)//1024}KB)")
                    logo_injected = True
                break
        if not logo_injected:
            print("  ⚠ Logo placeholder found but ai-doc-no-text.png not in folder — skipping")

    authors_json = [{"name": a["name"], "author_id": a["author_id"]} for a in authors]
    gs_data = []
    if gs_csv:
        with open(gs_csv) as f:
            for r in csv.DictReader(f):
                gs_data.append({"venue_name": r.get("venue_name", ""),
                                "h5_index": int(r["h5_index"]) if r.get("h5_index") else None,
                                "h5_median": int(r["h5_median"]) if r.get("h5_median") else None})

    embed = (
        f"const EMBEDDED_PAPERS={json.dumps(all_papers, separators=(',',':'), default=str)};\n"
        f"const EMBEDDED_AUTHORS={json.dumps(authors_json, separators=(',',':'))};\n"
        f"const EMBEDDED_GS={json.dumps(gs_data, separators=(',',':'))};\n"
        f"const EMBEDDED_HISTORY={json.dumps(history, separators=(',',':'))};\n"
        f'const EMBEDDED_DATE="{today}";\n'
        f'const EMBEDDED_SOURCE="{Path(author_xlsx).name}";\n'
    )
    html = html.replace("/*EMBEDDED_DATA_MARKER*/", embed)

    if not output_path:
        output_path = f"ai_doc_aquarium_{today}.html"
    Path(output_path).write_text(html, encoding="utf-8")
    size_kb = Path(output_path).stat().st_size / 1024
    print(f"\n✓ Done! Wrote {output_path} ({size_kb:.0f} KB)")
    print(f"  Open in browser or push to GitHub Pages as index.html")


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("""
AI-DOC Observatory — Unified Pipeline

Usage:
  python run_observatory.py authors.xlsx [options]

Options:
  --scimago FILE    SCImago CSV (from scimagojr.com → Download data)
  --jufo FILE       JUFO CSV (from jfp.csc.fi → search * → Download CSV)
  --gs FILE         Google Scholar metrics CSV (from scrape_gs_metrics.py)
  --jcr FILE        JCR Impact Factor CSV (from jcr.clarivate.com export)
  --template FILE   HTML template (observatory_aquarium.html)
  --output FILE     Output HTML filename
  --history FILE    History JSON file (default: ai_doc_history.json)
  --min-year N      Minimum publication year (default: 2023)
  --delay N         Seconds between SS API calls (default: 3)

Example:
  python run_observatory.py semantic_scholar_ids_2026-03-25.xlsx \\
    --scimago "scimagojr 2024.csv" \\
    --jufo jufo_channels.csv \\
    --gs google_scholar_metrics_2026-03-25.csv \\
    --jcr jcr_export.csv \\
    --output index.html
""")
        sys.exit(1)

    author_xlsx = sys.argv[1]
    kwargs = {}
    i = 2
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--scimago": kwargs["scimago_csv"] = sys.argv[i+1]; i += 2
        elif a == "--jufo": kwargs["jufo_csv"] = sys.argv[i+1]; i += 2
        elif a == "--gs": kwargs["gs_csv"] = sys.argv[i+1]; i += 2
        elif a == "--jcr": kwargs["jcr_csv"] = sys.argv[i+1]; i += 2
        elif a == "--template": kwargs["template_path"] = sys.argv[i+1]; i += 2
        elif a == "--output": kwargs["output_path"] = sys.argv[i+1]; i += 2
        elif a == "--history": kwargs["history_path"] = sys.argv[i+1]; i += 2
        elif a == "--min-year": kwargs["min_year"] = int(sys.argv[i+1]); i += 2
        elif a == "--delay": API_DELAY = float(sys.argv[i+1]); i += 2
        else: i += 1

    run(author_xlsx, **kwargs)
