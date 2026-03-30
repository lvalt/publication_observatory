#!/usr/bin/env python3
"""
AI-DOC Publication Aquarium — 8-Bit Fishing GUI
=================================================
A cute pixel-art fishing game interface that runs the observatory pipeline.
Watch fish get caught as papers are discovered!

Requirements:
    pip install requests pandas pillow
    (tkinter comes with Python)

Usage:
    python observatory_gui.py
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import math
import random
import time
import os
import sys
from pathlib import Path

# ─── Import the pipeline (same folder) ───
try:
    import run_observatory_26 as pipeline
except ImportError:
    pipeline = None

# ═══════════════════════════════════════════════════════
# 8-Bit Color Palette (from AI-DOC scheme)
# ═══════════════════════════════════════════════════════
C = {
    "deep":      "#001930",
    "ocean":     "#0b3c56",
    "teal":      "#2c6b86",
    "teal_lt":   "#3a8ba8",
    "foam":      "#fefefe",
    "glow":      "#4ecdc4",
    "glow_dim":  "#2a9d8f",
    "sand":      "#c4a35a",
    "sand_lt":   "#e0c97f",
    "coral":     "#eb4d4b",
    "warn":      "#f7b731",
    "seaweed":   "#1a5c3a",
    "seaweed_lt":"#2d8a56",
    "fish1":     "#4ecdc4",
    "fish2":     "#f7b731",
    "fish3":     "#eb4d4b",
    "fish4":     "#6bbcd4",
    "fish5":     "#e0c97f",
    "net":       "#8b7355",
    "net_lt":    "#a08860",
    "bubble":    "#6bbcd4",
    "white":     "#ffffff",
    "text":      "#d4eaf2",
    "text_dim":  "#7ca3b5",
}

FISH_COLORS = [C["fish1"], C["fish2"], C["fish3"], C["fish4"], C["fish5"]]
PIXEL = 4  # base pixel scale

# ═══════════════════════════════════════════════════════
# Pixel Art Helpers
# ═══════════════════════════════════════════════════════
def draw_pixel_rect(canvas, x, y, w, h, color):
    """Draw a pixel-scaled rectangle."""
    canvas.create_rectangle(x, y, x + w, y + h, fill=color, outline="", width=0)

def draw_pixel_text(canvas, x, y, text, color=None, size=10, anchor="w"):
    """Draw text with pixel-art friendly font."""
    if color is None: color = C["foam"]
    canvas.create_text(x, y, text=text, fill=color, font=("Courier", size, "bold"), anchor=anchor)


# ═══════════════════════════════════════════════════════
# Fish Sprite
# ═══════════════════════════════════════════════════════
class Fish:
    def __init__(self, canvas, x, y, color=None, size=1.0, speed=None):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.color = color or random.choice(FISH_COLORS)
        self.size = size
        self.speed = speed or random.uniform(0.6, 2.0)
        self.direction = -1  # swimming left
        self.wobble = random.uniform(0, math.pi * 2)
        self.wobble_speed = random.uniform(0.05, 0.12)
        self.wobble_amp = random.uniform(1, 3)
        self.caught = False
        self.catch_target_x = 0
        self.catch_target_y = 0
        self.items = []

    def draw(self):
        """Draw an 8-bit style fish."""
        for item in self.items:
            self.canvas.delete(item)
        self.items.clear()

        s = self.size
        p = PIXEL
        d = self.direction
        x, y = int(self.x), int(self.y)

        # Body (elliptical blob)
        bw = int(12 * s)
        bh = int(7 * s)
        body = self.canvas.create_oval(
            x - bw, y - bh, x + bw, y + bh,
            fill=self.color, outline=""
        )
        self.items.append(body)

        # Tail
        tx = x + (bw + 2) * d
        tail = self.canvas.create_polygon(
            tx, y,
            tx + int(6 * s) * d, y - int(5 * s),
            tx + int(6 * s) * d, y + int(5 * s),
            fill=self.color, outline=""
        )
        self.items.append(tail)

        # Eye
        ex = x - int(5 * s) * d
        ey = y - int(2 * s)
        eye = self.canvas.create_oval(
            ex - 2, ey - 2, ex + 2, ey + 2,
            fill=C["white"], outline=""
        )
        self.items.append(eye)
        pupil = self.canvas.create_oval(
            ex - 1 - d, ey - 1, ex + 1 - d, ey + 1,
            fill=C["deep"], outline=""
        )
        self.items.append(pupil)

    def update(self):
        self.wobble += self.wobble_speed

        if self.caught:
            # Swim toward catch target
            dx = self.catch_target_x - self.x
            dy = self.catch_target_y - self.y
            dist = max(math.sqrt(dx * dx + dy * dy), 0.1)
            if dist > 3:
                self.x += dx * 0.06
                self.y += dy * 0.06
            else:
                self.x = self.catch_target_x
                self.y = self.catch_target_y
            self.direction = 1 if dx > 0 else -1
        else:
            # Free swimming
            self.x += self.speed * self.direction
            self.y += math.sin(self.wobble) * self.wobble_amp

        self.draw()


# ═══════════════════════════════════════════════════════
# Bubble Particle
# ═══════════════════════════════════════════════════════
class Bubble:
    def __init__(self, canvas, x, y):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.r = random.uniform(2, 5)
        self.speed = random.uniform(0.3, 0.8)
        self.drift = random.uniform(-0.2, 0.2)
        self.item = None

    def update(self):
        if self.item:
            self.canvas.delete(self.item)
        self.y -= self.speed
        self.x += self.drift
        alpha_colors = [C["bubble"], C["teal_lt"], C["glow_dim"]]
        self.item = self.canvas.create_oval(
            self.x - self.r, self.y - self.r,
            self.x + self.r, self.y + self.r,
            fill="", outline=random.choice(alpha_colors), width=1
        )
        return self.y > -10


# ═══════════════════════════════════════════════════════
# Main GUI Application
# ═══════════════════════════════════════════════════════
class AquariumGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI-DOC Publication Aquarium 🐠")
        self.root.configure(bg=C["deep"])
        self.root.geometry("960x720")
        self.root.minsize(800, 600)

        # ─── State ───
        self.running = False
        self.fish_list = []
        self.caught_fish = []
        self.bubbles = []
        self.wave_offset = 0
        self.total_papers = 0
        self.total_authors = 0
        self.current_author = ""
        self.net_y = 100
        self.net_target_y = 100
        self.bobber_y = 0
        self.line_deployed = False
        self.frame = 0
        self.log_lines = []
        self.stats = {"Q1": 0, "Q2": 0, "JUFO3": 0, "JIF_Q1": 0}

        # ─── Config (file paths) ───
        self.authors_file = tk.StringVar(value="")
        self.scimago_file = tk.StringVar(value="")
        self.gs_file = tk.StringVar(value="")
        self.jcr_file = tk.StringVar(value="")
        self.jufo_file = tk.StringVar(value="")

        self.build_ui()
        self.animate()

    def build_ui(self):
        # Top bar
        topbar = tk.Frame(self.root, bg=C["ocean"], height=50)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="🐠 AI-DOC Publication Aquarium",
                 font=("Courier", 16, "bold"), fg=C["glow"], bg=C["ocean"]).pack(side="left", padx=16)

        self.status_label = tk.Label(topbar, text="Configure files and press START",
                                     font=("Courier", 10), fg=C["text_dim"], bg=C["ocean"])
        self.status_label.pack(side="right", padx=16)

        # Main area: canvas left, controls right
        main = tk.Frame(self.root, bg=C["deep"])
        main.pack(fill="both", expand=True)

        # Canvas (ocean scene)
        self.canvas = tk.Canvas(main, bg=C["deep"], highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        # Right panel
        right = tk.Frame(main, bg=C["ocean"], width=280)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # File selectors
        files_frame = tk.Frame(right, bg=C["ocean"])
        files_frame.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(files_frame, text="FILES", font=("Courier", 9, "bold"),
                 fg=C["glow"], bg=C["ocean"]).pack(anchor="w")

        self._add_file_row(files_frame, "Authors .xlsx *", self.authors_file, [("Excel", "*.xlsx *.xls")])
        self._add_file_row(files_frame, "SCImago .csv", self.scimago_file, [("CSV", "*.csv")])
        self._add_file_row(files_frame, "GS Metrics .csv", self.gs_file, [("CSV", "*.csv")])
        self._add_file_row(files_frame, "JCR .csv", self.jcr_file, [("CSV", "*.csv")])
        self._add_file_row(files_frame, "JUFO .csv", self.jufo_file, [("CSV", "*.csv")])

        # Start button
        self.start_btn = tk.Button(
            right, text="▶  START FISHING", font=("Courier", 12, "bold"),
            fg=C["deep"], bg=C["glow"], activebackground=C["glow_dim"],
            relief="flat", cursor="hand2", command=self.start_pipeline
        )
        self.start_btn.pack(fill="x", padx=10, pady=10, ipady=6)

        # Stats
        stats_frame = tk.Frame(right, bg=C["ocean"])
        stats_frame.pack(fill="x", padx=10)

        tk.Label(stats_frame, text="CATCH OF THE DAY", font=("Courier", 9, "bold"),
                 fg=C["glow"], bg=C["ocean"]).pack(anchor="w", pady=(5, 3))

        self.stats_text = tk.Label(
            stats_frame, text="Papers: 0  Authors: 0\nQ1: 0  JUFO3: 0  JIF Q1: 0",
            font=("Courier", 10), fg=C["text"], bg=C["deep"],
            justify="left", anchor="w", padx=8, pady=6
        )
        self.stats_text.pack(fill="x")

        # Log
        tk.Label(right, text="LOG", font=("Courier", 9, "bold"),
                 fg=C["glow"], bg=C["ocean"]).pack(anchor="w", padx=10, pady=(10, 3))

        log_frame = tk.Frame(right, bg=C["deep"])
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log_text = tk.Text(
            log_frame, font=("Courier", 8), fg=C["text_dim"], bg=C["deep"],
            insertbackground=C["glow"], wrap="word", state="disabled",
            relief="flat", borderwidth=0
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("ok", foreground=C["glow"])
        self.log_text.tag_configure("warn", foreground=C["warn"])
        self.log_text.tag_configure("err", foreground=C["coral"])
        self.log_text.tag_configure("info", foreground=C["teal_lt"])
        self.log_text.tag_configure("author", foreground=C["foam"])

        # Bottom bar
        bottom = tk.Frame(self.root, bg=C["ocean"], height=30)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)
        self.progress_label = tk.Label(bottom, text="", font=("Courier", 9),
                                        fg=C["text_dim"], bg=C["ocean"])
        self.progress_label.pack(side="left", padx=16)

        # Export button (hidden initially)
        self.export_btn = tk.Button(
            bottom, text="📥 Export & Push", font=("Courier", 9, "bold"),
            fg=C["deep"], bg=C["warn"], relief="flat", cursor="hand2",
            command=self.export_results
        )

    def _add_file_row(self, parent, label, var, filetypes):
        row = tk.Frame(parent, bg=C["ocean"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, font=("Courier", 8), fg=C["text_dim"],
                 bg=C["ocean"], width=14, anchor="w").pack(side="left")

        def pick():
            path = filedialog.askopenfilename(filetypes=filetypes + [("All", "*.*")])
            if path:
                var.set(path)
                btn.config(text="✓ " + Path(path).name[:15], fg=C["glow"])

        btn = tk.Button(row, text="Browse...", font=("Courier", 8),
                       fg=C["text"], bg=C["teal"], relief="flat",
                       cursor="hand2", command=pick)
        btn.pack(side="right")

    # ═══ Pipeline ═══
    def start_pipeline(self):
        if self.running:
            return
        if not self.authors_file.get():
            messagebox.showwarning("Missing file", "Please select the Authors .xlsx file!")
            return
        if not pipeline:
            messagebox.showerror("Missing module", "run_observatory.py not found in the same folder!")
            return

        self.running = True
        self.start_btn.config(state="disabled", text="🎣 FISHING...", bg=C["teal"])
        self.line_deployed = True
        self.total_papers = 0
        self.total_authors = 0
        self.caught_fish.clear()
        self.stats = {"Q1": 0, "Q2": 0, "JUFO3": 0, "JIF_Q1": 0}

        self.log("Starting pipeline...", "info")

        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()

    def _run_pipeline(self):
        """Run the actual pipeline in background thread."""
        try:
            # Monkey-patch the pipeline's print to capture output
            original_print = print
            gui = self

            # Build kwargs
            kwargs = {}
            if self.scimago_file.get(): kwargs["scimago_csv"] = self.scimago_file.get()
            if self.gs_file.get(): kwargs["gs_csv"] = self.gs_file.get()
            if self.jcr_file.get(): kwargs["jcr_csv"] = self.jcr_file.get()
            if self.jufo_file.get(): kwargs["jufo_csv"] = self.jufo_file.get()
            kwargs["output_path"] = "index.html"

            # We need to intercept the pipeline to get per-author results
            # Run a modified version that calls our callbacks
            self._run_pipeline_with_callbacks(self.authors_file.get(), **kwargs)

        except Exception as e:
            self.log(f"ERROR: {e}", "err")
        finally:
            self.root.after(0, self._pipeline_done)

    def _run_pipeline_with_callbacks(self, author_xlsx, **kwargs):
        """Modified pipeline that reports progress to the GUI."""
        min_year = pipeline.MIN_YEAR
        today = __import__("datetime").date.today().isoformat()
        history_path = pipeline.HISTORY_FILE

        # Step 1: Load authors
        self.log("[1/6] Loading authors...", "info")
        rows = pipeline.read_xlsx(author_xlsx)
        authors = []
        for r in rows:
            aid = str(r.get("author_id", "")).replace(".0", "").strip()
            status = str(r.get("status", "")).upper()
            name = r.get("name", "")
            if aid and status == "CONFIRMED":
                authors.append({"name": name, "author_id": aid})
        self.log(f"  {len(authors)} authors", "ok")

        # Step 2: Load rankings
        self.log("[2/6] Loading ranking datasets...", "info")
        sci_idx = pipeline.build_scimago_index(kwargs["scimago_csv"]) if kwargs.get("scimago_csv") else None
        jufo_idx = pipeline.build_jufo_index(kwargs["jufo_csv"]) if kwargs.get("jufo_csv") else None
        gs_idx = pipeline.build_gs_index(kwargs["gs_csv"]) if kwargs.get("gs_csv") else None
        jcr_idx = pipeline.build_jcr_index(kwargs["jcr_csv"]) if kwargs.get("jcr_csv") else None
        if sci_idx: self.log(f"  SCImago: {len(sci_idx['byIssn'])} ISSNs", "ok")
        if jufo_idx: self.log(f"  JUFO: {len(jufo_idx['byIssn'])} ISSNs", "ok")
        if gs_idx: self.log(f"  GS: {len(gs_idx['byName'])} venues", "ok")
        if jcr_idx: self.log(f"  JCR: {len(jcr_idx['byIssn'])} ISSNs", "ok")

        # Step 3: Fetch papers
        self.log(f"[3/6] Fetching papers (min year {min_year})...", "info")
        all_papers = []
        venue_cache = {}

        for i, a in enumerate(authors):
            self.root.after(0, lambda name=a["name"], idx=i, total=len(authors):
                self._update_progress(name, idx, total))

            papers = pipeline.fetch_author_papers(a["author_id"], min_year)

            for p in papers:
                pv = p.get("publicationVenue") or {}
                vn = pv.get("name") or p.get("venue") or ""
                vi = None
                issns = pv.get("issn") or pv.get("alternate_issns")
                if isinstance(issns, list) and issns: vi = issns[0]
                elif isinstance(issns, str): vi = issns

                ck = vi or vn
                if ck and ck not in venue_cache:
                    sci = pipeline.lookup_scimago(sci_idx, vn, vi)
                    jufo = pipeline.lookup_jufo(jufo_idx, vn, vi)
                    gs = pipeline.lookup_gs(gs_idx, vn)
                    jcr = pipeline.lookup_jcr(jcr_idx, vn, vi)
                    venue_cache[ck] = {**sci, **jufo, **gs, **jcr}
                vc = venue_cache.get(ck, {})
                ext = p.get("externalIds") or {}

                paper_data = {
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
                }
                all_papers.append(paper_data)

            # Report to GUI
            n = len(papers)
            self.root.after(0, lambda name=a["name"], count=n: self._author_done(name, count))
            self.log(f"  {a['name']}: {n} paper(s)", "author" if n > 0 else "warn")

            time.sleep(pipeline.API_DELAY)

        # Step 4: Save Excel
        self.log(f"[4/6] Saving Excel...", "info")
        import pandas as pd
        df = pd.DataFrame(all_papers)
        cols = ["author_name","author_id","title","year","publicationDate","venue","venue_issn","doi",
                "scimago_quartile","scimago_sjr","jufo_level","gs_h5_index","gs_h5_median","jif","jif_quartile","paper_id"]
        df = df[[c for c in cols if c in df.columns]]
        excel_path = f"papers_with_rankings_{today}.xlsx"
        df.to_excel(excel_path, index=False)
        self.log(f"  Saved {excel_path}", "ok")

        # Step 5: Update history
        self.log(f"[5/6] Updating history...", "info")
        hp = Path(history_path)
        history = __import__("json").loads(hp.read_text()) if hp.exists() else []
        snap = pipeline.build_snapshot(all_papers, today)
        history = [h for h in history if h["date"] != today]
        history.append(snap)
        history.sort(key=lambda h: h["date"])
        hp.write_text(__import__("json").dumps(history, indent=2))
        self.log(f"  {len(history)} snapshot(s)", "ok")

        # Step 6: Bake HTML
        self.log(f"[6/6] Baking HTML...", "info")
        output_path = kwargs.get("output_path", "index.html")

        template_path = None
        for c in [Path("observatory_aquarium.html"), Path("observatory_public.html")]:
            if c.exists():
                template_path = str(c)
                break

        if template_path:
            import json, csv as csv_mod, base64
            html = Path(template_path).read_text(encoding="utf-8")

            # Logo injection
            if "/*LOGO_BASE64*/" in html:
                for lp in [Path("ai-doc-no-text.png")]:
                    if lp.exists():
                        try:
                            from PIL import Image
                            import io
                            img = Image.open(lp)
                            img.thumbnail((300, 120), Image.LANCZOS)
                            buf = io.BytesIO()
                            img.save(buf, format='PNG', optimize=True)
                            html = html.replace("/*LOGO_BASE64*/", base64.b64encode(buf.getvalue()).decode())
                        except ImportError:
                            html = html.replace("/*LOGO_BASE64*/", base64.b64encode(lp.read_bytes()).decode())
                        break

            authors_json = [{"name": a["name"], "author_id": a["author_id"]} for a in authors]
            gs_data = []
            if kwargs.get("gs_csv"):
                with open(kwargs["gs_csv"]) as f:
                    for r in csv_mod.DictReader(f):
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
            Path(output_path).write_text(html, encoding="utf-8")
            self.log(f"  Wrote {output_path}", "ok")
        else:
            self.log("  ⚠ No template found — skipping HTML", "warn")

        # Final stats
        self.total_papers = len(all_papers)
        self.total_authors = len(set(p["author_name"] for p in all_papers))
        self.stats["Q1"] = sum(1 for p in all_papers if p.get("scimago_quartile") == "Q1")
        self.stats["Q2"] = sum(1 for p in all_papers if p.get("scimago_quartile") == "Q2")
        self.stats["JUFO3"] = sum(1 for p in all_papers if str(p.get("jufo_level")) == "3")
        self.stats["JIF_Q1"] = sum(1 for p in all_papers if p.get("jif_quartile") == "Q1")

        self.log(f"\n✓ Complete: {self.total_papers} papers, {self.total_authors} authors", "ok")

    def _update_progress(self, name, idx, total):
        self.current_author = name
        pct = int((idx / total) * 100)
        self.progress_label.config(text=f"[{idx+1}/{total}] {name} ({pct}%)")
        self.status_label.config(text=f"Fishing... {idx+1}/{total}")

    def _author_done(self, name, paper_count):
        """Called when an author's papers are fetched — spawn fish!"""
        self.total_papers += paper_count
        self.total_authors += 1
        self._update_stats()

        # Spawn fish for this author's papers
        cw = self.canvas.winfo_width() or 700
        ch = self.canvas.winfo_height() or 500
        water_top = int(ch * 0.25)

        for j in range(min(paper_count, 20)):  # cap visual fish
            x = cw + random.randint(20, 100)
            y = random.randint(water_top + 40, ch - 60)
            size = random.uniform(0.6, 1.2)
            fish = Fish(self.canvas, x, y, size=size)
            fish.direction = -1
            fish.speed = random.uniform(1.0, 2.5)

            # Set catch target (in the net area)
            net_x = cw * 0.15 + random.randint(-30, 30)
            net_y = water_top + 50 + len(self.caught_fish) * 3 + random.randint(-15, 15)
            net_y = min(net_y, ch - 80)

            # Fish swims in, then after some time gets "caught"
            fish._catch_delay = random.randint(30, 90)
            fish._catch_counter = 0
            fish.catch_target_x = net_x
            fish.catch_target_y = net_y

            self.fish_list.append(fish)

    def _pipeline_done(self):
        self.running = False
        self.line_deployed = False
        self.start_btn.config(state="normal", text="▶  START FISHING", bg=C["glow"])
        self.status_label.config(text=f"Done! {self.total_papers} papers caught 🐠")
        self.export_btn.pack(side="right", padx=16)
        self._update_stats()

    def _update_stats(self):
        self.stats_text.config(
            text=f"Papers: {self.total_papers}  Authors: {self.total_authors}\n"
                 f"SJR Q1: {self.stats['Q1']}  JUFO3: {self.stats['JUFO3']}\n"
                 f"JIF Q1: {self.stats['JIF_Q1']}"
        )

    def log(self, msg, tag=None):
        def _do():
            self.log_text.config(state="normal")
            if tag:
                self.log_text.insert("end", msg + "\n", tag)
            else:
                self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _do)

    def export_results(self):
        """Open the generated index.html and optionally git push."""
        if os.path.exists("index.html"):
            os.startfile("index.html") if sys.platform == "win32" else os.system("open index.html")

        if messagebox.askyesno("Push to GitHub?",
                               "Push index.html and ai_doc_history.json to GitHub?\n\n"
                               "(Requires git to be installed and configured)"):
            try:
                os.system('git add index.html ai_doc_history.json')
                today = __import__("datetime").date.today().isoformat()
                os.system(f'git commit -m "Update observatory {today}"')
                os.system('git push')
                self.log("Pushed to GitHub!", "ok")
            except Exception as e:
                self.log(f"Git error: {e}", "err")

    # ═══ Animation Loop ═══
    def animate(self):
        self.frame += 1
        canvas = self.canvas
        cw = canvas.winfo_width() or 700
        ch = canvas.winfo_height() or 500

        canvas.delete("bg")

        water_top = int(ch * 0.25)

        # Sky / above water gradient
        for i in range(water_top):
            frac = i / max(water_top, 1)
            r = int(0 + frac * 11)
            g = int(25 + frac * 35)
            b = int(48 + frac * 38)
            color = f"#{r:02x}{g:02x}{b:02x}"
            canvas.create_line(0, i, cw, i, fill=color, tags="bg")

        # Water
        for i in range(water_top, ch):
            frac = (i - water_top) / max(ch - water_top, 1)
            r = int(0 + frac * 0)
            g = int(40 - frac * 15)
            b = int(70 - frac * 20)
            color = f"#{max(r,0):02x}{max(g,0):02x}{max(b,0):02x}"
            canvas.create_line(0, i, cw, i, fill=color, tags="bg")

        # Waves
        self.wave_offset += 0.04
        for wx in range(0, cw, 3):
            wy = water_top + math.sin(wx * 0.03 + self.wave_offset) * 4
            canvas.create_oval(wx - 1, wy - 1, wx + 1, wy + 1,
                             fill=C["teal_lt"], outline="", tags="bg")

        # Seaweed
        for sx in [int(cw * 0.7), int(cw * 0.8), int(cw * 0.9), int(cw * 0.55)]:
            for seg in range(8):
                sy = ch - seg * 12
                sway = math.sin(self.frame * 0.03 + sx * 0.01 + seg * 0.5) * (4 + seg)
                col = C["seaweed"] if seg % 2 == 0 else C["seaweed_lt"]
                canvas.create_oval(sx + sway - 4, sy - 6, sx + sway + 4, sy + 6,
                                 fill=col, outline="", tags="bg")

        # Sand bottom
        for sx in range(0, cw, 3):
            sh = random.randint(0, 3) if self.frame % 60 == 0 else 1
            canvas.create_rectangle(sx, ch - 10, sx + 3, ch,
                                  fill=C["sand"] if sx % 6 < 3 else C["sand_lt"],
                                  outline="", tags="bg")

        # Fishing line & bobber
        if self.line_deployed:
            boat_x = int(cw * 0.15)
            # Boat (simple pixel boat)
            canvas.create_polygon(
                boat_x - 25, water_top - 5,
                boat_x - 30, water_top + 8,
                boat_x + 30, water_top + 8,
                boat_x + 25, water_top - 5,
                fill=C["net"], outline=C["net_lt"], tags="bg"
            )
            # Mast
            canvas.create_line(boat_x, water_top - 5, boat_x, water_top - 35,
                             fill=C["net_lt"], width=2, tags="bg")

            # Fishing line
            line_bottom = water_top + 80 + math.sin(self.frame * 0.05) * 10
            canvas.create_line(boat_x + 15, water_top - 25, boat_x + 60, line_bottom,
                             fill=C["text_dim"], width=1, dash=(3, 3), tags="bg")

            # Bobber
            bx = boat_x + 60
            by = line_bottom
            canvas.create_oval(bx - 4, by - 4, bx + 4, by + 4,
                             fill=C["coral"], outline=C["warn"], tags="bg")

            # Net (simple trapezoid)
            net_top_y = water_top + 60
            canvas.create_polygon(
                boat_x - 35, net_top_y,
                boat_x + 35, net_top_y,
                boat_x + 25, net_top_y + 80,
                boat_x - 25, net_top_y + 80,
                fill="", outline=C["net_lt"], width=2, dash=(4, 2), tags="bg"
            )
            # Net grid lines
            for ny in range(0, 80, 12):
                canvas.create_line(boat_x - 33 + ny * 0.1, net_top_y + ny,
                                 boat_x + 33 - ny * 0.1, net_top_y + ny,
                                 fill=C["net"], width=1, dash=(2, 3), tags="bg")

        # Bubbles
        if random.random() < 0.08:
            bx = random.randint(50, cw - 50)
            by = ch - 20
            self.bubbles.append(Bubble(canvas, bx, by))

        self.bubbles = [b for b in self.bubbles if b.update()]

        # Update fish
        for fish in self.fish_list:
            if not fish.caught:
                fish._catch_counter += 1
                if fish._catch_counter >= fish._catch_delay:
                    # Check if fish is on screen
                    if fish.x < cw * 0.6:
                        fish.caught = True
                        self.caught_fish.append(fish)
            fish.update()

            # Remove fish that swam off screen
        self.fish_list = [f for f in self.fish_list if f.x > -50 or f.caught]

        # Paper counter (big pixel text)
        if self.total_papers > 0:
            draw_pixel_text(canvas, cw - 20, 20, f"{self.total_papers}", C["glow"], size=24, anchor="ne")
            draw_pixel_text(canvas, cw - 20, 48, "papers caught", C["text_dim"], size=9, anchor="ne")

        # Current author
        if self.running and self.current_author:
            draw_pixel_text(canvas, cw // 2, 15, f"🎣 {self.current_author}",
                          C["foam"], size=11, anchor="n")

        self.root.after(33, self.animate)  # ~30 FPS


# ═══════════════════════════════════════════════════════
# Launch
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = AquariumGUI(root)
    root.mainloop()
