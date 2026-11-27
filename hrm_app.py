"""International HRM - Streamlit + SQLite (default) or PostgreSQL (set DATABASE_URL)
Run: pip install -r requirements.txt && streamlit run hrm_app.py
"""
import sqlite3, hashlib, io, html, calendar, hmac, re, os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones
import pandas as pd
import streamlit as st

DB = "hrm.db"
CODE = {"Present": "P", "Absent": "A", "Leave": "L", "Off": "O"}
REV = {v: k for k, v in CODE.items()}
LBL = {"P": "🟢 P", "A": "🔴 A", "L": "🟡 L", "O": "⚪ O"}


def _dmy(fn):
    def w(*a, **k):
        k.setdefault("format", "DD/MM/YYYY")
        try:
            return fn(*a, **k)
        except TypeError:
            k.pop("format", None)
            return fn(*a, **k)
    return w


try:
    from streamlit.delta_generator import DeltaGenerator
    DeltaGenerator.date_input = _dmy(DeltaGenerator.date_input)
except Exception:
    pass
st.date_input = _dmy(st.date_input)
st.set_page_config(page_title="HRM", layout="wide")
st.markdown("""<style>
.stApp{background:#eef5ef;color:#1b2b22}
.stApp h1,.stApp h2,.stApp h3{color:#1b2b22}
[data-testid="stSidebar"]{background:#14472f;width:205px !important;min-width:205px !important;z-index:1000000 !important}
[data-testid="stSidebar"] > div:first-child{width:205px !important}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],[data-testid="stSidebar"] section{padding-left:.6rem;padding-right:.6rem}
[data-testid="stSidebar"] *{color:#e8f5ec !important}
[data-testid="stSidebar"] .stButton button{background:transparent;border:1px solid #6fae8a}
.card{background:#fff;color:#1b2b22;border-radius:14px;padding:16px 18px;box-shadow:0 2px 10px rgba(20,71,47,.08)}
.kpi{display:flex;align-items:center;gap:14px}
.kpi .ic{font-size:24px;width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center}
.kpi .lb{font-size:13px;color:#6b7c72}
.kpi .v{font-size:28px;font-weight:700}
.ttl{font-weight:600;font-size:16px;margin-bottom:10px}
.row{display:flex;align-items:center;gap:18px}
.donut{width:130px;height:130px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.donut div{width:84px;height:84px;border-radius:50%;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:12px;color:#6b7c72}
.donut b{font-size:24px;color:#1b2b22}
.leg{font-size:13px;line-height:2;flex:1}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}
.ci{display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #eef2ee}
.av{width:36px;height:36px;border-radius:50%;background:#2e7d4f;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600}
.badge{margin-left:auto;background:#e3f4e8;color:#2e7d4f;padding:2px 12px;border-radius:8px;font-size:12px}
.bars{display:flex;align-items:flex-end;gap:12px;height:130px;margin-top:8px}
.bars div{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;font-size:11px;font-weight:700;color:#ff2e93}
.bars span{width:70%;background:#2e7d4f;border-radius:4px 4px 0 0;display:block}
[data-baseweb="select"]>div{background:#eaf5ee;border:1.5px solid #2e7d4f}
[data-baseweb="tag"]{background-color:#2e7d4f !important;color:#fff !important}
.stButton>button:hover,[data-testid="stDownloadButton"] button:hover,[data-testid="stFormSubmitButton"] button:hover{background:#ff2e93 !important;color:#fff !important;border-color:#ff2e93 !important}
[role="option"]:hover,li[role="option"]:hover{background:#ff7ab8 !important;color:#fff !important}
[data-testid="stSidebar"] label:hover{background:rgba(255,46,147,.40) !important;border-radius:8px}
[data-testid="stTabs"] button:hover,[data-testid="stExpander"] summary:hover{color:#ff2e93 !important}
</style>""", unsafe_allow_html=True)
_COL = {"co": "#1f3a5f", "sec": "#e67e22", "spn": "#7d3c98", "lab": "#117a8b", "pay": "#2ea05a", "st": "#b7950b", "dt": "#64748b"}
# each coloured frame is preceded by an invisible marker (<span class="cb cb-co">); CSS colours the frame that follows it
_css = '[data-testid="stElementContainer"]:has(.cb){display:none}.element-container:has(.cb){display:none}'
for _k, _c in _COL.items():
    for _w in ('[data-testid="stElementContainer"]', ".element-container"):
        _s = f"{_w}:has(.cb-{_k}) + {_w}"
        _css += (f'{_s}{{background:{_c};border-radius:14px;padding:10px 12px 12px;box-shadow:0 2px 6px rgba(0,0,0,.14)}}'
                 f'{_s} label p{{color:#fff !important;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}'
                 f'{_s} [data-baseweb="tag"]{{background-color:{_c} !important;color:#fff !important}}')
st.markdown("<style>" + _css + "</style>", unsafe_allow_html=True)


def _db_url():
    u = os.environ.get("DATABASE_URL", "")
    if not u:
        try:
            u = str(st.secrets.get("DATABASE_URL", ""))
        except Exception:
            u = ""
    return u


DBURL = _db_url()
PG = DBURL.startswith("postgres")
_QC = {}   # SELECT results inside ONE script run; any write clears it


@st.cache_resource(show_spinner=False)
def _pool(url):
    import numpy as np
    from psycopg2.extensions import AsIs, register_adapter
    from psycopg2.pool import ThreadedConnectionPool
    for t_ in (np.int64, np.int32, np.bool_):
        register_adapter(t_, AsIs)
    return ThreadedConnectionPool(1, 8, url)


def _clean(p):
    """numpy numbers -> Python numbers, NaN -> NULL (both databases)."""
    out = []
    for v in p:
        if hasattr(v, "item") and not isinstance(v, (str, bytes)):
            v = v.item()
        if isinstance(v, float) and v != v:
            v = None
        out.append(v)
    return tuple(out)


def _pg_sql(sql):
    """SQLite style (?) -> PostgreSQL style (%s); CREATE / ALTER types translated."""
    if sql.lstrip().upper().startswith(("CREATE", "ALTER")):
        sql = sql.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY").replace(" REAL", " DOUBLE PRECISION")
        sql = sql.replace("ADD COLUMN ", "ADD COLUMN IF NOT EXISTS ")
    return sql.replace("%", "%%").replace("?", "%s")


def _run_pg(sql, p, fetch):
    import psycopg2
    pool = _pool(DBURL)
    for attempt in (0, 1):
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_pg_sql(sql), p)
                cols = [d[0] for d in cur.description] if fetch else None
                rows = cur.fetchall() if fetch else None
            conn.commit()
            pool.putconn(conn)
            return pd.DataFrame(rows, columns=cols) if fetch else None
        except (psycopg2.OperationalError, psycopg2.InterfaceError):   # stale / sleeping connection: retry once
            pool.putconn(conn, close=True)
            if attempt:
                raise
        except Exception:
            conn.rollback()
            pool.putconn(conn)
            raise


def _run(sql, p, fetch):
    p = _clean(p)
    if PG:
        return _run_pg(sql, p, fetch)
    with sqlite3.connect(DB, timeout=30) as c:
        c.execute("PRAGMA foreign_keys=ON")
        cur = c.execute(sql, p)
        if fetch:
            return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        c.commit()


_RO = {"E": True, "D": True}   # write permission of the CURRENT menu page (set after the menu is chosen)


def _guard(sql):
    """Stop a write when this user has no Edit / Delete permission on the current menu."""
    u = sql.lstrip().upper()
    if "INTO SETTINGS" in u:
        return
    if (u.startswith(("INSERT", "UPDATE")) and not _RO["E"]) or (u.startswith("DELETE") and not _RO["D"]):
        st.error("🔒 You do not have permission for this action on this menu (Edit / Delete is switched off for your user). "
                 "Ask the Admin.")
        st.stop()


def q(sql, p=(), fetch=True):
    key = None
    if fetch:
        try:
            key = (sql, tuple(p))
            hash(key)
        except TypeError:
            key = None
        if key is not None and key in _QC:
            return _QC[key].copy()
    else:
        _guard(sql)
        _QC.clear()
    df = _run(sql, p, fetch)
    if fetch and key is not None:
        _QC[key] = df.copy()
    return df


def q_many(sql, rows):
    """One statement for many rows in ONE transaction (fast, also on a remote database)."""
    if not rows:
        return
    _guard(sql)
    rows = [_clean(r) for r in rows]
    _QC.clear()
    if PG:
        from psycopg2.extras import execute_batch
        pool = _pool(DBURL)
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                execute_batch(cur, _pg_sql(sql), rows, page_size=500)
            conn.commit()
            pool.putconn(conn)
        except Exception:
            conn.rollback()
            pool.putconn(conn)
            raise
    else:
        with sqlite3.connect(DB, timeout=30) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.executemany(sql, rows)
            c.commit()


def pw(p):
    return hashlib.sha256(("hrm$" + p).encode()).hexdigest()


def rate_steps(join, d, ny, rep):
    """Increments due on day d: one per completed `ny` years of service (rep) or just one."""
    if ny <= 0 or not join:
        return 0
    try:
        jd = date.fromisoformat(str(join)[:10])
    except ValueError:
        return 0
    y = d.year - jd.year - ((d.month, d.day) < (jd.month, jd.day))
    return 0 if y < ny else (y // ny if rep else 1)


def eff_rate(rate, join, d):
    """Monthly basic in force on day d = base basic + the service increments."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return rate + float(S("inc_amount")) * rate_steps(join, d, int(float(S("inc_years"))), S("inc_repeat") == "Yes")


def ot_rate_of(rate, pay_type, ot_rate, ref, join=None):
    """OT rate/hour: the employee's own OT rate, else hourly rate (Hourly) or daily rate/std hrs x multiplier (Monthly)."""
    if ot_rate and ot_rate > 0:
        return round(ot_rate, 2)
    if pay_type != "Monthly":
        return round(rate, 2)
    d = date.fromisoformat(ref)
    if join:
        rate = eff_rate(rate, join, d)
    n = calendar.monthrange(d.year, d.month)[1]
    wd_m = n - sum(date(d.year, d.month, k).weekday() == int(S("weekend")) for k in range(1, n + 1))
    return round(rate / wd_m / float(S("std_hours")) * float(S("ot_mult")), 2)


def hol_rate(hol, day, cid, sid, kid):
    """None = not a special holiday for this company/section/kofil; else its rate per hour (0 = use the OT rate)."""
    for h in hol.itertuples():
        if (h.from_day <= day <= h.to_day and (pd.isna(h.company_id) or h.company_id == cid)
                and (pd.isna(h.dept_id) or h.dept_id == sid) and (pd.isna(h.sponsor_id) or h.sponsor_id == kid)):
            return float(h.rate or 0)
    return None


def eosb(r, upto):
    """End-of-service: half month wage/yr for first 5 yrs, one month wage/yr after (Saudi labour law style)."""
    yrs = max((upto - datetime.strptime(r.join_date, "%Y-%m-%d").date()).days / 365.25, 0)
    wage = eff_rate(r.rate, r.join_date, upto) if r.pay_type == "Monthly" else r.rate * float(S("std_hours")) * float(S("work_days"))
    return round(yrs, 2), round(wage, 2), round(wage / 2 * min(yrs, 5) + wage * max(yrs - 5, 0), 2)


def payslip_pdf(r, d1, d2):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 16); c.drawString(50, y, f"{S('company')} - PAYSLIP"); y -= 25
    c.setFont("Helvetica", 11); c.drawString(50, y, f"Period: {d1} to {d2}"); y -= 30
    money = {"Monthly Basic Rate", "Hr Rate", "OT Rate", "Basic", "Food", "Special Allow", "Other Allow", "OT Pay", "Wknd OT", "Hol Pay", "Ex.hrs Pay", "Allowances", "Bonus", "Advance", "Absent Ded", "Deduction", "Net"}
    for k in r.index:
        if k in ("Invoice", "Bank", "Cash"):
            continue
        c.setFont("Helvetica-Bold" if k == "Net" else "Helvetica", 11)
        c.drawString(50, y, k)
        c.drawString(250, y, f"{maybe_dmy(r[k])}" + (f" {S('currency')}" if k in money else ""))
        y -= 18
    c.drawString(50, y - 20, "Employee signature: ____________        HR signature: ____________")
    c.save()
    return b.getvalue()


TRF_SEL = """SELECT t.id, t.day, e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no,
    fc.name AS from_company, fd.name AS from_section, fs.name AS from_kofil, tc.name AS company, td.name AS section,
    ts.name AS sponsor, e.labour_type, e.pay_type, t.note FROM transfers t JOIN employees e ON e.id=t.emp_id """
TRF_J = """LEFT JOIN companies fc ON fc.id=t.from_company LEFT JOIN departments fd ON fd.id=t.from_dept
    LEFT JOIN sponsors fs ON fs.id=t.from_sponsor LEFT JOIN companies tc ON tc.id=t.to_company
    LEFT JOIN departments td ON td.id=t.to_dept LEFT JOIN sponsors ts ON ts.id=t.to_sponsor"""
TRF_SQL = TRF_SEL + TRF_J + " WHERE t.day BETWEEN ? AND ? ORDER BY t.day DESC, e.code"


def trf_df(d1, d2, flt=()):
    df = apply_f(q(TRF_SQL, (d1, d2)), *flt)
    return df.rename(columns={"company": "to_company", "section": "to_section", "sponsor": "to_kofil"})


def do_transfer(r, co, dp, sp, day, note, upd):
    """Move one employee to a new company / section / kofil (None = unchanged) and keep the history."""
    nn = lambda v: None if pd.isna(v) else int(v)
    cur = (nn(r.company_id), nn(r.dept_id), nn(r.sponsor_id))
    new = (co if co is not None else cur[0], dp if dp is not None else cur[1], sp if sp is not None else cur[2])
    # freeze the OLD place on every earlier attendance row that has no place saved, so history never follows the employee
    q("UPDATE attendance SET company_id=COALESCE(company_id,?), dept_id=COALESCE(dept_id,?), sponsor_id=COALESCE(sponsor_id,?) "
      "WHERE emp_id=?", (*cur, int(r.id)), fetch=False)
    q("INSERT INTO transfers(emp_id,day,from_company,from_dept,from_sponsor,to_company,to_dept,to_sponsor,note) "
      "VALUES(?,?,?,?,?,?,?,?,?)", (int(r.id), str(day), *cur, *new, note), fetch=False)
    q("UPDATE employees SET company_id=?, dept_id=?, sponsor_id=? WHERE id=?", (*new, int(r.id)), fetch=False)
    if upd:
        sets = [(c_, v_) for c_, v_ in (("company_id", co), ("dept_id", dp), ("sponsor_id", sp)) if v_ is not None]
        if sets:
            q("UPDATE attendance SET " + ",".join(f"{c_}=?" for c_, _ in sets) + " WHERE emp_id=? AND day>=?",
              (*[v_ for _, v_ in sets], int(r.id), str(day)), fetch=False)


def emp_history(r):
    """(timeline of joining/transfers, places worked from attendance) for one employee."""
    tr = q(TRF_SEL + TRF_J + " WHERE t.emp_id=? ORDER BY t.day, t.id", (int(r.id),))
    f0 = tr.iloc[0] if len(tr) else None
    ev = [{"Date": r.join_date, "Event": "Joined", "From": "-",
           "Company": (f0.from_company if f0 is not None else r.company) or "-",
           "Section": (f0.from_section if f0 is not None else r.section) or "-",
           "Kofil": (f0.from_kofil if f0 is not None else r.sponsor) or "-", "Note": ""}]
    for _, t in tr.iterrows():
        ev.append({"Date": t.day, "Event": "Transferred",
                   "From": f"{t.from_company or '-'} / {t.from_section or '-'} / {t.from_kofil or '-'}",
                   "Company": t.company or "-", "Section": t.section or "-", "Kofil": t.sponsor or "-", "Note": t.note or ""})
    wk = q("""SELECT COALESCE(c.name,c0.name,'-') AS company, COALESCE(d.name,d0.name,'-') AS section,
        COALESCE(sa.name,s0.name,'-') AS kofil, MIN(a.day) AS from_day, MAX(a.day) AS to_day,
        SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present, SUM(CASE WHEN a.status='Leave' THEN 1 ELSE 0 END) AS leave,
        SUM(CASE WHEN a.status='Absent' THEN 1 ELSE 0 END) AS absent,
        SUM(COALESCE(a.hours,0)) AS normal_hrs, SUM(COALESCE(a.ot_hours,0)) AS ot_hrs
        FROM attendance a JOIN employees e ON e.id=a.emp_id
        LEFT JOIN companies c ON c.id=a.company_id LEFT JOIN companies c0 ON c0.id=e.company_id
        LEFT JOIN departments d ON d.id=a.dept_id LEFT JOIN departments d0 ON d0.id=e.dept_id
        LEFT JOIN sponsors sa ON sa.id=a.sponsor_id LEFT JOIN sponsors s0 ON s0.id=e.sponsor_id
        WHERE a.emp_id=? GROUP BY 1, 2, 3 ORDER BY from_day""", (int(r.id),))
    wk["normal_hrs"], wk["ot_hrs"] = wk.normal_hrs.astype(float).round(2), wk.ot_hrs.astype(float).round(2)
    wk["total_hrs"] = wk.normal_hrs + wk.ot_hrs
    return pd.DataFrame(ev), wk


def doc_pdf(title, hdr, sections, appr=()):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    b, sty = io.BytesIO(), getSampleStyleSheet()
    els = [Paragraph(f"<b>{S('company')} - {title}</b>", sty["Title"]), Paragraph(hdr, sty["Normal"]), Spacer(1, 8)]
    for h, d in sections:
        d = fmt_dates(d)
        data = [[str(c) for c in d.columns]] + [["" if pd.isna(v) else (f"{v:,.2f}" if isinstance(v, float) else str(v))[:34]
                                                  for v in row] for row in d.itertuples(index=False)]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(S("pdf_head_bg"))),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(S("pdf_head_fg"))), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        els += [Paragraph(f"<b>{h}</b>", sty["Heading4"]), t, Spacer(1, 10)]
    lg = _logo()
    foot = lambda c, d: _draw_logo(c, landscape(A4)[0], landscape(A4)[1], 24, lg)
    els += [_sign_block(landscape(A4)[0] - 48, appr)]
    SimpleDocTemplate(b, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24 + (lg[2] + 4 if lg else 0),
                      bottomMargin=24).build(els, onFirstPage=foot, onLaterPages=foot)
    return b.getvalue()


BULK_SQL = ("INSERT INTO attendance(emp_id,day,status,hours,ot_hours,company_id,dept_id,sponsor_id) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(emp_id,day) DO UPDATE SET status=excluded.status,hours=excluded.hours,ot_hours=excluded.ot_hours")


def bulk_places():
    """{emp_id: [(day, from_c, from_d, from_s, to_c, to_d, to_s)]} - where each person worked on which date."""
    t = q("SELECT emp_id, day, from_company, from_dept, from_sponsor, to_company, to_dept, to_sponsor FROM transfers ORDER BY day, id")
    out = {}
    for x in t.itertuples(index=False):
        out.setdefault(int(x.emp_id), []).append((x.day, _id(x.from_company), _id(x.from_dept), _id(x.from_sponsor),
                                                  _id(x.to_company), _id(x.to_dept), _id(x.to_sponsor)))
    return out


def place_on(tr, eid, ds, cur):
    """(company, section, kofil) of this person on that date, from the transfer history."""
    t = tr.get(eid)
    if not t:
        return cur
    last = None
    for x in t:
        if x[0] <= ds:
            last = x
    return (last[4], last[5], last[6]) if last else (t[0][1], t[0][2], t[0][3])


def bulk_build(e, d1, d2, force=None):
    """Grid for the chosen staff and period: saved records are shown as they are; other working days start as P,
    Fridays / special holidays start as O and are saved too. Any date (past or future) can be saved."""
    days = [d1 + timedelta(k) for k in range((d2 - d1).days + 1)]
    att = q("SELECT emp_id, day, status FROM attendance WHERE day BETWEEN ? AND ?", (str(d1), str(d2)))
    ex = {(int(t.emp_id), t.day): CODE.get(t.status, "P") for t in att.itertuples(index=False)}
    hol, tr, we = q("SELECT * FROM holidays"), bulk_places(), int(S("weekend"))
    dn, do_ = float(S("def_normal")), float(S("def_ot"))
    labs = [f"{d:%d} {d:%a}" for d in days]
    rows = []
    for r in e.itertuples(index=False):
        cur = (_id(r.company_id), _id(r.dept_id), _id(r.sponsor_id))
        rec = {"id": int(r.id), "Code": r.code, "Name": r.name, "Iqama ID": r.id_no or "", "Pay Type": r.pay_type,
               "Company": r.company or "", "Section": r.section or "", "Sponsor": r.sponsor or "",
               "Normal Hrs/day": dn, "OT Hrs/day": do_}
        for d, lab in zip(days, labs):
            ds = d.isoformat()
            code = ex.get((int(r.id), ds))
            if code is None:
                off = d.weekday() == we or hol_rate(hol, ds, *place_on(tr, int(r.id), ds, cur)) is not None
                code = "O" if off else "P"
            if force:
                code = force
            rec[lab] = code
        rows.append(rec)
    return pd.DataFrame(rows), days, labs, set(ex), tr


def bulk_rows(orig, ed, days, labs, ex_keys, tr, e, rewrite_p=False):
    """Records to write: new cells, and changed saved cells (untouched saved cells keep their own hours)."""
    cur_by = {int(r.id): (_id(r.company_id), _id(r.dept_id), _id(r.sponsor_id)) for r in e.itertuples(index=False)}
    out = []
    for i in range(len(ed)):
        er, orow = ed.iloc[i], orig.iloc[i]
        eid = int(er["id"])
        for d, lab in zip(days, labs):
            new, old = er[lab], orow[lab]
            if new is None or pd.isna(new) or new == "":
                continue
            ds = d.isoformat()
            if (eid, ds) in ex_keys and new == old and not (rewrite_p and new == "P"):
                continue
            pr = new == "P"
            c_, s_, k_ = place_on(tr, eid, ds, cur_by[eid])
            out.append((eid, ds, REV[new], float(er["Normal Hrs/day"]) if pr else 0.0,
                        float(er["OT Hrs/day"]) if pr else 0.0, c_, s_, k_))
    return out


def _selcol():
    try:
        return st.column_config.SelectboxColumn(options=["", "P", "A", "L", "O"], width="small")
    except TypeError:
        return st.column_config.SelectboxColumn(options=["", "P", "A", "L", "O"])


SCHEMA_VERSION = "2026-11-27a"   # change this whenever tables/settings change
DEFAULTS = {"company": "My Company", "currency": "SAR", "timezone": "Asia/Riyadh",
                "std_hours": "8", "work_days": "26", "ot_mult": "1.5", "date_fmt": "%d-%m-%Y", "gosi_pct": "0", "gosi_nat": "Saudi", "vat_pct": "15", "weekend": "4", "def_normal": "10", "def_ot": "2", "inc_years": "2", "inc_amount": "100", "inc_repeat": "No", "bulk_on": "Yes", "marquee_on": "Yes", "marquee_text": "RAFIK IT SOLUTION", "logo_b64": "", "logo_t1": "LABOUR", "logo_t2": "MANPOWER SUPPLY", "logo_t3": "SKILLED WORKFORCE · RECRUITMENT", "logo_pos": "Left", "logo_h": "40", "prepared_by": "", "pdf_head_bg": "#e3efe7", "pdf_head_fg": "#14472f", "pdf_tot_bg": "#fff4cf", "pdf_tot_fg": "#7c2d12"}


def init():
    for s in [
        "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)",
        "CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS sponsors(id INTEGER PRIMARY KEY, name TEXT UNIQUE, phone TEXT)",
        """CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT,
            dept_id INT, sponsor_id INT, labour_type TEXT, pay_type TEXT, rate REAL,
            nationality TEXT, id_no TEXT, phone TEXT, join_date TEXT, active INT DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY, emp_id INT, day TEXT,
            status TEXT, in_t TEXT, out_t TEXT, hours REAL, UNIQUE(emp_id, day))""",
        "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, role TEXT)",
        "CREATE TABLE IF NOT EXISTS adjustments(id INTEGER PRIMARY KEY, emp_id INT, day TEXT, kind TEXT, amount REAL, note TEXT)",
        """CREATE TABLE IF NOT EXISTS leaves(id INTEGER PRIMARY KEY, emp_id INT, ltype TEXT,
            start TEXT, \"end\" TEXT, days INT, status TEXT)""",
    ]:
        q(s, fetch=False)
    defaults = DEFAULTS
    for k, v in defaults.items():
        q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT DO NOTHING", (k, v), fetch=False)
    q("CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, name TEXT UNIQUE, vat TEXT)", fetch=False)
    q("CREATE TABLE IF NOT EXISTS costs(id INTEGER PRIMARY KEY, day TEXT, category TEXT, emp_id INT, company_id INT, amount REAL, note TEXT)", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS holidays(id INTEGER PRIMARY KEY, from_day TEXT, to_day TEXT, company_id INT, dept_id INT,
        sponsor_id INT, rate REAL DEFAULT 0, note TEXT)""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS commissions(id INTEGER PRIMARY KEY, person TEXT, phone TEXT, company_id INT, dept_id INT,
        sponsor_id INT, rate REAL DEFAULT 0, note TEXT, active INT DEFAULT 1)""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY, emp_id INT, day TEXT, from_company INT, from_dept INT,
        from_sponsor INT, to_company INT, to_dept INT, to_sponsor INT, note TEXT)""", fetch=False)
    for t_, c_ in [("employees", "id_expiry TEXT"), ("employees", "company_id INT"), ("employees", "food_allow REAL DEFAULT 0"),
                   ("employees", "ot_rate REAL DEFAULT 0"), ("employees", "bill_rate REAL DEFAULT 0"),
                   ("employees", "pay_mode TEXT DEFAULT 'Bank'"), ("attendance", "company_id INT"), ("attendance", "dept_id INT"), ("attendance", "ot_hours REAL"), ("employees", "passport_no TEXT"), ("attendance", "sponsor_id INT"), ("companies", "cycle_day INT DEFAULT 1"), ("employees", "special_allow REAL DEFAULT 0"), ("employees", "other_allow REAL DEFAULT 0"), ("companies", "exh_mode TEXT DEFAULT 'Off'"), ("companies", "exh_hours REAL DEFAULT 10"), ("sponsors", "approved_by TEXT"), ("users", "perms TEXT")]:
        try:
            q(f"ALTER TABLE {t_} ADD COLUMN {c_}", fetch=False)
        except Exception:
            pass
    if q("SELECT COUNT(*) AS n FROM users").n[0] == 0:
        q("INSERT INTO users(username,pw,role) VALUES(?,?,?)", ("admin", pw("admin123"), "Admin"), fetch=False)
    if not PG:
        q("PRAGMA journal_mode=WAL", fetch=False)   # several people can read while one saves
    for ix in ("attendance(day)", "attendance(company_id)", "adjustments(day)", "adjustments(emp_id)", "costs(day)",
               "leaves(emp_id)", "transfers(emp_id)", "employees(company_id)"):
        q(f"CREATE INDEX IF NOT EXISTS ix_{ix.replace('(', '_').replace(')', '')} ON {ix}", fetch=False)
    for nm_, col_ in (("ux_emp_idno", "id_no"), ("ux_emp_passport", "passport_no")):   # one person = one Iqama / passport
        try:
            q(f"CREATE UNIQUE INDEX IF NOT EXISTS {nm_} ON employees({col_}) WHERE {col_} IS NOT NULL AND {col_} <> ''", fetch=False)
        except Exception:
            pass          # old duplicates still exist: the Employees / Payroll pages list them until they are fixed


@st.cache_resource(show_spinner=False)
def _init_once(url, ver):
    init()
    return True


def init_guard():
    """Create / upgrade the tables once per server start (not on every click)."""
    if st.session_state.get("_db_ready") != SCHEMA_VERSION:
        _init_once(DBURL or DB, SCHEMA_VERSION)
        st.session_state["_db_ready"] = SCHEMA_VERSION


def S(k):
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    if len(r):
        return r.iloc[0, 0]
    d = DEFAULTS.get(k, "")
    if k in DEFAULTS:
        q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT DO NOTHING", (k, d), fetch=False)
    return d


def today():
    return datetime.now(ZoneInfo(S("timezone"))).date()


def hrs(i, o):
    try:
        a = datetime.strptime(i, "%H:%M")
        b = datetime.strptime(o, "%H:%M")
        d = (b - a).total_seconds() / 3600
        return round(d + 24 if d < 0 else d, 2)
    except Exception:
        return 0.0


def emp_df(active=True):
    return q("""SELECT e.id, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, e.pay_mode, e.rate, e.food_allow, e.special_allow, e.other_allow, e.ot_rate, e.bill_rate, e.nationality, e.id_no, e.passport_no, e.phone, e.join_date, e.id_expiry, e.company_id, e.dept_id, e.sponsor_id, e.active
        FROM employees e LEFT JOIN companies c ON c.id=e.company_id LEFT JOIN departments d ON d.id=e.dept_id
        LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE (? IS NULL OR e.active=?)""", (None if active is None else int(bool(active)),) * 2)


def save_emp(d):
    cols = list(d)
    q(f"INSERT INTO employees({','.join(cols)}) VALUES({','.join('?' * len(cols))}) ON CONFLICT(code) DO UPDATE SET "
      + ",".join(f"{k}=excluded.{k}" for k in cols if k != "code"), tuple(d.values()), fetch=False)


def _nk(v):
    """Compare key: no spaces, upper case (so 'ab 12' = 'AB12')."""
    return re.sub(r"\s+", "", str(v if v is not None and str(v) != "nan" else "")).upper()


def emp_conflicts(code, idn, pas, skip_id=None):
    """Messages for every employee that already uses this Code / Iqama ID / Passport no. (empty list = all free)."""
    df = q("SELECT id, code, name, id_no, passport_no FROM employees")
    out = []
    for fld, val, label in (("code", code, "Code"), ("id_no", idn, "ID / Iqama no."), ("passport_no", pas, "Passport no.")):
        k = _nk(val)
        if not k:
            continue
        for r in df.itertuples():
            if r.id != skip_id and _nk(getattr(r, fld)) == k:
                out.append(f"{label} '{str(val).strip()}' is already used by {r.name} (code {r.code})")
    return out


def dup_report():
    """Employees that share the same Iqama ID or Passport no. (data entered before the rule existed)."""
    df = q("SELECT code, name, id_no, passport_no, active FROM employees")
    rows = []
    for fld, label in (("id_no", "ID / Iqama no."), ("passport_no", "Passport no.")):
        d = df[df[fld].map(_nk) != ""].assign(_k=lambda x: x[fld].map(_nk))
        for k, g in d.groupby("_k"):
            if len(g) > 1:
                rows.append({"Field": label, "Value": g[fld].iloc[0], "Persons": len(g),
                             "Employees": " | ".join(f"{r.code} {r.name}" for r in g.itertuples())})
    return pd.DataFrame(rows)


def show_dups():
    """Red warning on the pages that matter (Employees, Payroll, Dashboard) while duplicates exist."""
    d = dup_report()
    if d.empty:
        return
    st.error(f"⚠ DUPLICATE: {len(d)} Iqama / Passport number(s) are used by more than one person. "
             "Correct them in Employees > Edit (a number must belong to ONE person only).")
    tbl(d, False)


def _norm_cb(key):
    """'All' is an option inside the box: choosing it clears the rest; choosing a specific item removes 'All'."""
    new, prev = st.session_state.get(key, []), st.session_state.get(key + "_prev", [])
    if "All" in new and len(new) > 1:
        new = ["All"] if "All" not in prev else [x for x in new if x != "All"]
    st.session_state[key] = st.session_state[key + "_prev"] = new


def msel(label, options, key, default_all=False, ph="All"):
    """Multiselect that has an 'All' option inside the box. Returns the selected list."""
    options = list(options)
    if key not in st.session_state:
        st.session_state[key] = st.session_state[key + "_prev"] = ["All"] if default_all else []
    st.session_state[key] = [x for x in st.session_state[key] if x == "All" or x in options]
    kind = key.rsplit("_", 1)[-1]
    if kind in _COL:
        st.markdown(f'<span class="cb cb-{kind}"></span>', unsafe_allow_html=True)
    try:
        st.multiselect(label, ["All"] + options, key=key, on_change=_norm_cb, args=(key,), placeholder=ph)
    except TypeError:   # very old Streamlit without 'placeholder'
        st.multiselect(label, ["All"] + options, key=key, on_change=_norm_cb, args=(key,))
    return list(st.session_state[key])


def eff(sel, options=()):
    """'All' (or every item) selected = no filter, so rows with empty company/section/kofil are kept too."""
    return [] if "All" in sel or (options and set(options) <= set(sel)) else sel


def dbox(col, label, value, key):
    """Date input inside a coloured frame (same look as the select frames)."""
    with col:
        st.markdown('<span class="cb cb-dt"></span>', unsafe_allow_html=True)
        return st.date_input(label, value, key=key)


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def cycle_range(y, m, cday):
    """Pay period of the month named by its START: day 21 of November -> 20 December."""
    start = date(y, m, min(max(int(cday or 1), 1), 28))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, date(ny, nm, start.day) - timedelta(days=1)


def pay_groups(y, m, co):
    """[(start, end, [companies])] - companies with the same pay cycle share one period."""
    cm = q("SELECT name, COALESCE(cycle_day,1) AS cd FROM companies")
    cd = dict(zip(cm.name, cm.cd))
    groups = {}
    for n in (co or cm.name.tolist()):
        groups.setdefault(cycle_range(y, m, cd.get(n, 1)), []).append(n)
    if not co:   # staff with no company assigned yet
        groups.setdefault(cycle_range(y, m, 1), []).append("-")
    return [(str(a), str(b), v) for (a, b), v in sorted(groups.items())]


def dsel(col, label, options, index, key):
    with col:
        st.markdown('<span class="cb cb-dt"></span>', unsafe_allow_html=True)
        return st.selectbox(label, options, index=index, key=key)


def pay_filters(key):
    """Company, Sponsor/Kofil, ... then 'For the month of' (or custom dates). The pay period of every selected
    company is filled in from its cycle start day; results are shown group by group."""
    cos, secs, spns = (q(f"SELECT name FROM {t}").name.tolist() for t in ("companies", "departments", "sponsors"))
    c = st.columns(5)
    with c[0]:
        co = eff(msel("Company", cos, key + "_co"), cos)
    with c[1]:
        spn = eff(msel("Sponsor / Kofil", spns, key + "_spn"), spns)
    with c[2]:
        sec = eff(msel("Section", secs, key + "_sec"), secs)
    with c[3]:
        lt = eff(msel("Labour", ["Company", "Outside"], key + "_lab"), ["Company", "Outside"])
    with c[4]:
        pt = eff(msel("Pay type", ["Monthly", "Hourly"], key + "_pay"), ["Monthly", "Hourly"])
    td = today()
    c = st.columns([1, 0.8, 1.1, 1, 1])
    mo = dsel(c[0], "For the month of", MONTHS, td.month - 1, key + "_mo")
    yr = dsel(c[1], "Year", list(range(2024, 2031)), min(max(td.year - 2024, 0), 6), key + "_yr")
    custom = c[2].checkbox("Use custom dates", key=key + "_cu")
    if custom:
        d1, d2 = dbox(c[3], "From", td.replace(day=1), key + "a"), dbox(c[4], "To", td, key + "b")
        groups = [(str(d1), str(d2), co)]
    else:
        groups = pay_groups(yr, MONTHS.index(mo) + 1, co)
        fm = lambda x: date.fromisoformat(x).strftime("%d %b %Y")
        st.info(f"For the month of **{mo.upper()}-{yr}**   |   Period:  " +
                "   ||   ".join(f"**{', '.join(v)}**: {fm(a)} to {fm(b)}" for a, b, v in groups))
    qs = search_box("🔎 Search name / code / Iqama / passport", key + "h")
    st.session_state["_grp_" + key], st.session_state["_cyc_" + key] = groups, not custom
    st.session_state["_monlab"] = "" if custom else f"For the month of {mo}-{yr}"
    return min(g[0] for g in groups), max(g[1] for g in groups), sec, lt, pt, spn, co, qs


def filters(key):
    """Every page, ONE row: From, To, Company, Section, Labour, Pay type, Sponsor/Kofil (+ search below)."""
    cos, secs, spns = (q(f"SELECT name FROM {t}").name.tolist() for t in ("companies", "departments", "sponsors"))
    c = st.columns([1, 1, 1.15, 1.15, 1, 1, 1.15])
    d1 = dbox(c[0], "From", today().replace(day=1), key + "a")
    d2 = dbox(c[1], "To", today(), key + "b")
    with c[2]:
        co = eff(msel("Company", cos, key + "_co"), cos)
    with c[3]:
        sec = eff(msel("Section", secs, key + "_sec"), secs)
    with c[4]:
        lt = eff(msel("Labour", ["Company", "Outside"], key + "_lab"), ["Company", "Outside"])
    with c[5]:
        pt = eff(msel("Pay type", ["Monthly", "Hourly"], key + "_pay"), ["Monthly", "Hourly"])
    with c[6]:
        spn = eff(msel("Sponsor / Kofil", spns, key + "_spn"), spns)
    qs = search_box("🔎 Search name / code / Iqama / passport", key + "h")
    st.session_state["_monlab"] = ""
    return str(d1), str(d2), sec, lt, pt, spn, co, qs


def apply_f(df, sec=(), lt=(), pt=(), spn=(), co=(), qs=""):
    for col, v in (("section", sec), ("labour_type", lt), ("pay_type", pt), ("sponsor", spn), ("company", co)):
        if v and col in df:
            df = df[df[col].isin(v)]
    cols = [c for c in ("code", "name", "employee", "id_no", "iqama_id", "passport_no", "phone", "Code", "Name", "Iqama ID", "Passport No") if c in df]
    if qs and cols:
        m = pd.Series(False, index=df.index)
        for c in cols:
            m |= df[c].astype(str).str.contains(qs, case=False, na=False, regex=False)
        df = df[m]
    return df


RATECOLS = {"rate", "Rate", "Monthly Basic Rate", "Hr Rate", "OT Rate", "OT_Rate", "ot_rate", "bill_rate", "Rate/hr", "active",
            "id", "monthly_basic_rate", "current_basic", "hr_rate", "Years", "Monthly wage", "cycle_day"}


def add_total(df, total=True):
    """S/L serial numbers + a TOTAL row (sum of every numeric column except rates)."""
    if df.empty:
        return df
    d = fmt_dates(df).copy()
    fc = d.columns[1] if d.columns[0] == "S/L" and len(d.columns) > 1 else d.columns[0]
    if d[fc].astype(str).str.upper().str.startswith("TOTAL").any():
        return d
    d.insert(0, "S/L", [str(i) for i in range(1, len(d) + 1)]) if "S/L" not in d.columns else d.__setitem__("S/L", d["S/L"].astype(str))
    isn = lambda c: pd.api.types.is_numeric_dtype(d[c]) and not pd.api.types.is_bool_dtype(d[c])
    num = [c for c in d.columns if isn(c) and c not in RATECOLS and "rate" not in str(c).lower()]
    if not total or not num:
        return d
    t = {c: (float("nan") if isn(c) else "") for c in d.columns}
    t.update({c: round(float(d[c].sum()), 2) for c in num})
    t[next(c for c in d.columns if c != "S/L" and not isn(c))] = f"TOTAL ({len(d)})"
    ints = [c for c in d.columns if pd.api.types.is_integer_dtype(d[c])]
    out = pd.concat([d, pd.DataFrame([t])], ignore_index=True)
    for c in ints:   # counts (days, persons) stay whole numbers
        out[c] = out[c].astype("Int64")
    return out


def tbl(df, total=True):
    """Show a table with S/L and a coloured, bold TOTAL row."""
    d = add_total(df, total)
    try:
        isT = d.astype(str).apply(lambda r: r.str.startswith("TOTAL").any(), axis=1)
        sty = d.style.format(precision=2, na_rep="").apply(
            lambda r: ["background-color:#fde68a;color:#7c2d12;font-weight:800" if isT[r.name] else "" for _ in r], axis=1)
        st.dataframe(sty, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(d, use_container_width=True, hide_index=True)


def search_box(label, key):
    """Search that filters while you type (needs the 'streamlit-keyup' package; falls back to Enter-to-search)."""
    try:
        from st_keyup import st_keyup
        return st_keyup(label, key=key, debounce=250) or ""
    except Exception:
        return st.text_input(label, key=key)


def sign(df):
    df = df.copy()
    df["Signature"], df["Finger"] = "", ""
    return df


def dmy(x):
    try:
        return date.fromisoformat(str(x)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(x)


ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
EMPTY = ("", "None", "nan", "NaT")


def date_cols(df):
    """Text columns whose filled cells are all ISO dates (2026-11-20)."""
    out = []
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):   # object or string dtype
            v = df[c].dropna().astype(str)
            v = v[~v.isin(EMPTY)]
            if len(v) and v.map(lambda x: bool(ISO_RE.fullmatch(x))).all():
                out.append(c)
    return out


def fmt_dates(df):
    """Show every date column as DD/MM/YYYY."""
    cols = date_cols(df)
    if not cols:
        return df
    df = df.copy()
    for c in cols:
        df[c] = df[c].map(lambda v: dmy(v) if str(v) not in EMPTY else v)
    return df


def to_iso(v):
    """DD/MM/YYYY (or YYYY-MM-DD) -> YYYY-MM-DD, None when it is not a real date."""
    v = str(v).strip()
    if ISO_RE.fullmatch(v):
        return v
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", v)
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else None
    except ValueError:
        return None


def maybe_dmy(v):
    return dmy(v) if isinstance(v, str) and ISO_RE.fullmatch(v) else v


class Hdr(str):
    """Header text that also carries its parts (company, kofil, month) for the custom print."""


def hdr_of(d1, d2, sec=(), lt=(), pt=(), spn=(), co=(), qs=""):
    j = lambda x: ", ".join(x) if x else "All"
    h = Hdr(f"Period: {dmy(d1)} to {dmy(d2)}   |   Company: {j(co)}   |   Kofil: {j(spn)}   |   Section: {j(sec)}   |   "
            f"Labour: {j(lt)}   |   Pay type: {j(pt)}")
    h.co, h.kofil = j(co), j(spn)
    h.left = [f"Period from: {dmy(d1)}  to  {dmy(d2)}", f"Section: {j(sec)}", f"Labour: {j(lt)}", f"Pay type: {j(pt)}"]
    h.month = st.session_state.get("_monlab", "") or f"{dmy(d1)} to {dmy(d2)}"
    h.sponsors = list(spn)
    return h


FONTS = {"Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
         "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
         "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique")}
STYLES = ["Regular", "Bold", "Italic", "Bold Italic"]


@st.cache_resource(show_spinner=False)
def _font_index():
    """{family: {style: .ttf path}} found in the 'fonts' folder next to this file and in the system font folders."""
    import os
    import re
    idx = {}
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = os.getcwd()
    for d in (os.path.join(here, "fonts"), "/usr/share/fonts", os.path.expanduser("~/.fonts")):
        for root, _, fs in os.walk(d):
            for f in fs:
                m = re.match(r"^([A-Za-z0-9]+)(?:-(Regular|Bold|Italic|BoldItalic|Oblique|BoldOblique))?\.ttf$", f)
                if not m:
                    continue
                stl = {"Oblique": "Italic", "BoldOblique": "BoldItalic"}.get(m.group(2), m.group(2)) or "Regular"
                if re.search(r"(Bold|Italic|Oblique|Emoji|Math)", m.group(1)) and not m.group(2):
                    continue                       # separate weight files / symbol fonts are not families
                fam = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", m.group(1))
                for a_, b_ in (("Deja Vu", "DejaVu"), ("Sans3", "Sans 3"), ("DMSans", "DM Sans")):
                    fam = fam.replace(a_, b_)
                idx.setdefault(fam, {}).setdefault(stl, os.path.join(root, f))
    return {k: v for k, v in idx.items() if "Regular" in v}


def font_families():
    return list(FONTS) + [f for f in sorted(_font_index()) if f not in FONTS]


def _fonts(family="Helvetica", style="Regular"):
    if family in FONTS:
        f = FONTS[family]
        return f[STYLES.index(style) if style in STYLES else 0], f[1]   # body font, bold font (header / TOTAL row)
    idx = _font_index().get(family)
    if not idx:
        return _fonts("Helvetica", style)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    def reg(k):
        path = idx.get(k) or idx["Regular"]
        nm = f"{family}-{k if k in idx else 'Regular'}"
        if nm not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(nm, path))
        return nm
    want = {"Regular": "Regular", "Bold": "Bold", "Italic": "Italic", "Bold Italic": "BoldItalic"}.get(style, "Regular")
    return reg(want), reg("Bold")


def approvers(hdr, df):
    """[(kofil, approved-by name)] for the kofil(s) of this document."""
    names = list(getattr(hdr, "sponsors", []) or [])
    if not names:
        for c in ("Sponsor", "sponsor", "Kofil", "kofil", "to_kofil"):
            if c in df.columns:
                names = [v for v in df[c].dropna().astype(str).unique() if v and v != "-" and not v.startswith("TOTAL")]
                break
    m = {n: a for n, a in q("SELECT name, approved_by FROM sponsors").values.tolist()}
    return [(n, m[n]) for n in names if m.get(n)]


def _draw_approved(c, W, appr, m):
    """(old bottom-right stamp - not used any more; the signature block now sits right under the TOTAL row)"""
    return


def _sign_block(width, appr):
    """'Prepared by' (left) and 'Approved by' + kofil approver name (right), right under the last row of the table."""
    from reportlab.platypus import Flowable
    prep = str(S("prepared_by") or "")

    class _Sign(Flowable):
        def __init__(self):
            super().__init__()
            self.width, self.height = width, 34

        def wrap(self, aw, ah):
            return self.width, self.height

        def draw(self):
            c, h = self.canv, self.height
            c.setFont("Helvetica", 8)
            c.drawString(0, h - 9, "Prepared by")
            c.setFont("Helvetica-Bold", 11)
            c.drawString(0, h - 24, prep)
            x = self.width
            for spn_, name in appr:
                c.setFont("Helvetica", 8)
                c.drawRightString(x, h - 9, "Approved by" + (f"  ({spn_})" if len(appr) > 1 else ""))
                c.setFont("Helvetica-Bold", 11)
                c.drawRightString(x, h - 24, name)
                x -= 190
    return _Sign()


def _logo():
    """(image, icon width, height, position, info) - logo picture + the three text lines from Settings, or None."""
    t = [str(S(k) or "").strip() for k in ("logo_t1", "logo_t2", "logo_t3")]
    ir, iw_ = None, 0.0
    lh = float(S("logo_h") or 40)
    if S("logo_b64"):
        try:
            import base64
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(io.BytesIO(base64.b64decode(S("logo_b64"))))
            w0, h0 = ir.getSize()
            iw_ = lh * w0 / h0
        except Exception:
            ir = None
    if ir is None and not any(t):
        return None
    from reportlab.pdfbase.pdfmetrics import stringWidth
    s1, s2, s3 = lh * 0.17, lh * 0.25, lh * 0.15
    pad = lh * 0.12
    wd = [stringWidth(t[0], "Helvetica-Bold", s1) + 2 * pad if t[0] else 0,
          stringWidth(t[1], "Helvetica-Bold", s2) if t[1] else 0, stringWidth(t[2], "Helvetica", s3) if t[2] else 0]
    tw = max(wd)
    gap = lh * 0.22 if (ir is not None and tw) else 0
    return ir, iw_, lh, S("logo_pos"), dict(t=t, sz=(s1, s2, s3), pad=pad, tw=tw, gap=gap, total=iw_ + gap + tw)


def _draw_logo(c, W, H, m, lg):
    """Logo (picture + your text lines) on the top row of every page: left / centre / right as chosen in Settings."""
    if not lg:
        return
    ir, iw_, h, pos, f = lg
    x0 = m if pos == "Left" else (W - m - f["total"] if pos == "Right" else (W - f["total"]) / 2)
    top = H - m
    c.saveState()
    if ir is not None:
        c.drawImage(ir, x0, top - h, iw_, h, mask="auto")
    t, (s1, s2, s3), tw = f["t"], f["sz"], f["tw"]
    if any(t):
        x = x0 + iw_ + f["gap"]
        hb, hm, ht = s1 * 1.75, s2 * 1.2, s3 * 1.3
        th = (hb + 2 if t[0] else 0) + (hm + 2 if t[1] else 0) + (3 if t[1] and t[2] else 0) + (ht if t[2] else 0)
        y = top - max((h - th) / 2, 0)
        if t[0]:
            bw = f["tw"] if False else c.stringWidth(t[0], "Helvetica-Bold", s1) + 2 * f["pad"]
            c.setFillColorRGB(0.878, 0.078, 0.478)
            c.roundRect(x, y - hb, bw, hb, hb / 2, stroke=0, fill=1)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", s1)
            c.drawString(x + f["pad"], y - hb + (hb - s1) / 2 + s1 * 0.12, t[0])
            y -= hb + 2
        if t[1]:
            c.setFillColorRGB(0.055, 0.231, 0.161)
            c.setFont("Helvetica-Bold", s2)
            c.drawString(x, y - s2 * 0.95, t[1])
            y -= hm + 2
        if t[1] and t[2]:
            c.setStrokeColorRGB(0.96, 0.64, 0)
            c.setLineWidth(1)
            c.line(x, y + 1, x + tw, y + 1)
            y -= 3
        if t[2]:
            c.setFillColorRGB(0.29, 0.416, 0.357)
            c.setFont("Helvetica", s3)
            c.drawString(x, y - s3 * 0.95, t[2])
    c.restoreState()


def _pdf_fit(data, W, H, m, top, fs_max=8.0, check_h=True, bottom=None, fonts=("Helvetica", "Helvetica-Bold"), fixed=False,
             bold_last=False):
    """Largest font (>= 4pt) where every column is as wide as its widest text; returns font size and column widths."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    n, availw = len(data[0]), W - 2 * m - 2
    availh = H - (m if bottom is None else bottom) - top
    bold = lambda j: j == 0 or (bold_last and j == len(data) - 1)
    base = [max(stringWidth(r_[i], fonts[1] if bold(j) else fonts[0], 1) for j, r_ in enumerate(data)) for i in range(n)]
    fs = fs_max
    while not fixed and fs > 4:
        if sum(b * fs + 5 for b in base) <= availw and (not check_h or (fs * 1.15 + 3) * len(data) <= availh):
            break
        fs -= 0.25
    wid = [b * fs + 5 for b in base]
    k = availw / sum(wid) if sum(wid) > availw else min(availw / sum(wid), 1.5)
    return fs, [w * k for w in wid]


def _pdf_clip(data, wid, fs, fonts=("Helvetica", "Helvetica-Bold"), bold_last=False):
    """Cut text that is wider than its column (with '..'), so columns never overlap."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    out = []
    for j, row in enumerate(data):
        fn, new = fonts[1] if (j == 0 or (bold_last and j == len(data) - 1)) else fonts[0], []
        for t_, w in zip(row, wid):
            while len(t_) > 1 and stringWidth(t_, fn, fs) > w - 3:
                t_ = t_[:-3] + ".." if len(t_) > 3 else t_[:-1]
            new.append(t_)
        out.append(new)
    return out


def _pdf_style(fs, istot, rowpad=1.5, fonts=("Helvetica", "Helvetica-Bold")):
    from reportlab.lib import colors
    st_ = [("FONTSIZE", (0, 0), (-1, -1), fs), ("FONTNAME", (0, 0), (-1, -1), fonts[0]), ("FONTNAME", (0, 0), (-1, 0), fonts[1]),
           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(S("pdf_head_bg"))), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(S("pdf_head_fg"))),
           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9aa5a0")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("TOPPADDING", (0, 0), (-1, -1), rowpad), ("BOTTOMPADDING", (0, 0), (-1, -1), rowpad),
           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]
    if istot:   # TOTAL row: bold, coloured, thicker line above
        st_ += [("FONTNAME", (0, -1), (-1, -1), fonts[1]), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(S("pdf_tot_bg"))),
                ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor(S("pdf_tot_fg"))), ("LINEABOVE", (0, -1), (-1, -1), 1.0, colors.HexColor(S("pdf_tot_fg")))]
    return st_


def _pdf_data(df, cap=40):
    fmt = lambda v: "" if pd.isna(v) else (f"{v:,.2f}" if isinstance(v, float) else str(v))
    return [[str(c) for c in df.columns]] + [[fmt(v)[:cap] for v in row] for row in df.itertuples(index=False)]


def df_pdf(df, title, hdr=""):
    """One landscape page whenever possible; every column is as wide as its text, nothing overlaps."""
    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    df = fmt_dates(df)
    data = _pdf_data(df)
    istot = len(data) > 1 and any(c.startswith("TOTAL") for c in data[-1])
    appr, m = getattr(hdr, "appr", []), 16
    bottom = m + 46                       # room kept for the Prepared by / Approved by line under the table
    lg = _logo()
    off = lg[2] + 4 if lg else 0
    fonts = _fonts()
    for ps in ([landscape(A4)] if len(df.columns) <= 14 else []) + [landscape(A3)]:
        fs, wid = _pdf_fit(data, ps[0], ps[1], m, 88 + off, bottom=bottom, fonts=fonts, bold_last=istot)
        if fs >= 6:
            break
    t = Table(_pdf_clip(data, wid, fs, fonts, istot), colWidths=wid, repeatRows=1)
    t.setStyle(TableStyle(_pdf_style(fs, istot, 1.5, fonts)))
    sty = getSampleStyleSheet()
    sm = ParagraphStyle("sm", parent=sty["Normal"], fontSize=8, leading=10)
    foot = lambda c, d: _draw_logo(c, ps[0], ps[1], m, lg)
    b = io.BytesIO()
    SimpleDocTemplate(b, pagesize=ps, leftMargin=m, rightMargin=m, topMargin=m + off, bottomMargin=m).build([
        Paragraph(f"<b>{S('company')} - {title}</b>", ParagraphStyle("h", parent=sty["Title"], fontSize=14, leading=16, spaceAfter=2)),
        Paragraph(str(hdr), sm), Paragraph(f"Printed {dmy(today())}  |  {len(df) - (1 if istot else 0)} rows", sm),
        Spacer(1, 4), t, Spacer(1, 8), _sign_block(sum(wid), appr)], onFirstPage=foot, onLaterPages=foot)
    return b.getvalue()


def df_pdf_custom(df, cols, rowh, hdr, title, paper="A4", fit=False, family="Helvetica", style="Regular", fsize=0):
    """Only the chosen columns, your row height / font / size, a header on EVERY page (client company big + bold, kofil bold,
    'For the month of ...'; period / section / labour / pay type at the top left) and 'Approved by' at the bottom right."""
    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Table, TableStyle
    d = fmt_dates(df)
    istot = len(d) > 0 and any(str(v).startswith("TOTAL") for v in d.iloc[-1].tolist())
    data = _pdf_data(d[[c for c in d.columns if c in cols]], 30)
    if istot and not any(c.startswith("TOTAL") for c in data[-1]):   # the label column was not chosen: label the row anyway
        i0 = next((i for i, c in enumerate(data[-1]) if c == ""), 0)
        data[-1][i0] = "TOTAL" if data[-1][i0] == "" else "TOTAL " + data[-1][i0]
    W, H = landscape(A3 if paper == "A3" else A4)
    appr, m, top = getattr(hdr, "appr", []), 18, 96
    lg = _logo()
    off = lg[2] + 9 if lg else 0
    top += off
    bottom = m + 46                       # room kept for the Prepared by / Approved by line under the table
    fonts = _fonts(family, style)
    if fit:
        rowh = max(8, min(rowh, (H - top - bottom) / len(data)))
    auto = min(11.0, max(4.5, rowh * 0.5))
    fs, wid = _pdf_fit(data, W, H, m, top, fsize if fsize > 0 else auto, check_h=False, fonts=fonts, fixed=fsize > 0, bold_last=istot)
    t = Table(_pdf_clip(data, wid, fs, fonts, istot), colWidths=wid, rowHeights=[rowh] * len(data), repeatRows=1)
    t.setStyle(TableStyle(_pdf_style(fs, istot, 0, fonts)))
    lines = [(getattr(hdr, "co", "All"), "Helvetica-Bold", 17), (f"Sponsor / Kofil: {getattr(hdr, 'kofil', 'All')}", "Helvetica-Bold", 12),
             (getattr(hdr, "month", ""), "Helvetica-Bold", 11)]

    def head(c, doc):
        c.saveState()
        _draw_logo(c, W, H, m, lg)
        y = H - 26 - off
        for txt, fn, sz in lines:
            while sz > 7 and stringWidth(txt, fn, sz) > W - 360:
                sz -= 0.5
            c.setFont(fn, sz)
            c.drawCentredString(W / 2, y, txt)
            y -= sz + 5
        c.setFont("Helvetica", 8)
        for i, ln in enumerate(getattr(hdr, "left", [str(hdr)])):
            c.drawString(m, H - 20 - off - i * 10, ln)
        c.drawRightString(W - m, H - 20 - off, f"{S('company')} - {title}")
        c.drawRightString(W - m, H - 30 - off, f"Page {doc.page}   |   Printed {dmy(today())}")
        c.restoreState()

    b = io.BytesIO()
    doc = BaseDocTemplate(b, pagesize=(W, H), leftMargin=m, rightMargin=m, topMargin=top, bottomMargin=m)
    doc.addPageTemplates([PageTemplate(frames=[Frame(m, m, W - 2 * m, H - top - m, id="f", leftPadding=0,
                                                      rightPadding=0, topPadding=0, bottomPadding=0)], onPage=head)])
    from reportlab.platypus import Spacer
    doc.build([t, Spacer(1, 8), _sign_block(sum(wid), appr)])
    return b.getvalue()


def download(df, name, hdr="", uid=""):
    df = add_total(df)
    if not isinstance(hdr, Hdr):
        hdr = Hdr(str(hdr))
    hdr.appr = approvers(hdr, df)
    c = st.columns([1, 1.3, 1.3, 6])
    c[0].download_button("⬇ CSV", df.to_csv(index=False).encode("utf-8-sig"), f"{name}_{today()}.csv", "text/csv",
                         key="csv_" + name + uid)
    try:
        c[1].download_button("⬇ PDF (print)", df_pdf(df, name.replace("_", " "), hdr), f"{name}_{today()}.pdf",
                             "application/pdf", key="pdf_" + name + uid)
    except ImportError:
        c[1].caption("pip install reportlab")
        return
    if c[2].checkbox("🖨 Custom print", key="cp_" + name + uid):
        cc = st.columns([5, 1.2, 1, 1.4])
        cols = cc[0].multiselect("Columns to print (only these are printed)", list(df.columns), default=list(df.columns),
                                 key="cpc_" + name + uid)
        rh = cc[1].number_input("Row height (px)", 8, 300, 22, key="cph_" + name + uid)
        paper = cc[2].selectbox("Paper", ["A4", "A3"], key="cpp_" + name + uid)
        fit = cc[3].checkbox("Fit on one page", key="cpf_" + name + uid)
        c2 = st.columns([1.3, 1.3, 1.6, 4])
        fam = c2[0].selectbox("Font", font_families(), key="cpfa_" + name + uid)
        sty = c2[1].selectbox("Font style", STYLES, key="cpst_" + name + uid)
        fsz = c2[2].number_input("Font size (px, 0 = auto)", 0.0, 40.0, 0.0, 0.5, key="cpfs_" + name + uid)
        st.download_button("⬇ Custom PDF", df_pdf_custom(df, cols, rh, hdr, name.replace("_", " "), paper, fit, fam, sty, fsz),
                           f"{name}_custom_{today()}.pdf", "application/pdf", key="cpd_" + name + uid)


PCOLS = ["Code", "Name", "Join Date", "Iqama ID", "Passport No", "Company", "Section", "Sponsor", "Labour", "Pay", "Mode",
         "Monthly Basic Rate", "Hr Rate", "OT Rate", "Days", "Leave", "Absent", "No Work", "Normal Hrs", "OT Hrs", "Wknd Hrs",
         "Hol Hrs", "Total Hrs", "Basic", "Food", "Special Allow", "Other Allow", "OT Pay", "Wknd OT", "Hol Pay", "Ex Days",
         "Ex.hrs Pay", "Allowances", "Bonus", "Advance", "Absent Ded", "Deduction", "Net", "Bank", "Cash", "Invoice"]
PVIEW = [c for c in PCOLS if c != "Invoice"]
SUMC = ["Days", "Leave", "Absent", "No Work", "Normal Hrs", "OT Hrs", "Wknd Hrs", "Hol Hrs", "Total Hrs", "Basic", "Food",
        "Special Allow", "Other Allow", "OT Pay", "Wknd OT", "Hol Pay", "Ex Days", "Ex.hrs Pay", "Allowances", "Bonus",
        "Advance", "Absent Ded", "Deduction", "Net", "Bank", "Cash", "Invoice"]


def _wd(y, m, we):
    n = calendar.monthrange(y, m)[1]
    return n - sum(date(y, m, k).weekday() == we for k in range(1, n + 1))


def view_pay(p):
    d = p[PVIEW].copy()
    for c in ("Monthly Basic Rate", "Hr Rate"):
        d[c] = d[c].where(d[c] != 0, "")
    return sign(d)


def _isna(v):
    return v is None or (isinstance(v, float) and v != v)


def _id(v):
    return None if _isna(v) else int(v)


def calc_payroll(d1, d2, sec=(), lt=(), pt=(), spn=(), co=(), qs="", cyc=False, merge=True):
    """Monthly staff (per month, or per pay period when cyc):
      working days = days - Fridays - special holidays (for that company / kofil / section)
      Basic = sum of (basic in force that day / working days) over present + leave working days. The basic in force grows
        by the service increment (Settings: +amount after every N years from the joining date).
      Food, Other allowance = amount / working days x (present + leave + NO-WORK days); Special allowance is FIXED
      Absent working day (A, or not marked): basic / total days of the month is cut from basic AND the same amount is deducted again as a penalty
      No-work day (O): that day's basic is not paid, but NO penalty and NO food / allowance deduction
      Full month present: Bonus = basic / total days of the month.
      Extra-hour pay (per company): a day with more than N hours pays one hour of basic = basic / (N x days of the month)
      Work on Friday = OT rate; work on a special holiday = holiday rate (0 = OT rate), all hours.
    Hourly staff: normal hours x rate, OT / Friday hours x OT rate (own, else normal rate), holiday hours x holiday rate.
    Plain Python loops (no per-employee pandas work): thousands of employees take seconds."""
    e = apply_f(emp_df(None), (), lt, pt, (), (), qs)   # deactivated staff stay in old periods
    att = q("SELECT emp_id, day, status, hours, ot_hours, company_id, dept_id, sponsor_id FROM attendance WHERE day BETWEEN ? AND ?", (d1, d2))
    adj = q("SELECT emp_id, kind, amount FROM adjustments WHERE day BETWEEN ? AND ?", (d1, d2))
    hol = [(h.from_day, h.to_day, _id(h.company_id), _id(h.dept_id), _id(h.sponsor_id), h.rate)
           for h in q("SELECT * FROM holidays").itertuples()]
    cn, sn, kn = (dict(q(f"SELECT id,name FROM {t}").values) for t in ("companies", "departments", "sponsors"))
    exc = q("SELECT id, exh_mode, exh_hours FROM companies")
    ex_cfg = {int(i): (m_ if isinstance(m_, str) else "Off", 10.0 if _isna(h_) else float(h_))
              for i, m_, h_ in zip(exc.id, exc.exh_mode, exc.exh_hours)}
    nm = lambda d, k: "-" if k is None else d.get(int(k), "-")
    std, otm, we = float(S("std_hours")), float(S("ot_mult")), int(S("weekend"))
    gp, gn = float(S("gosi_pct")), S("gosi_nat").strip().lower()
    inc_y, inc_a, inc_rep = int(float(S("inc_years"))), float(S("inc_amount")), S("inc_repeat") == "Yes"
    D1, D2 = date.fromisoformat(d1), date.fromisoformat(d2)
    by_emp, adj_by = {}, {}
    for t in att.itertuples(index=False):
        by_emp.setdefault(int(t.emp_id), []).append(t)
    for t in adj.itertuples(index=False):
        adj_by.setdefault(int(t.emp_id), []).append((t.kind, 0.0 if _isna(t.amount) else float(t.amount)))
    hm, wkc = {}, {}

    def hrate(day, cid, sid, kid):   # None = not a special holiday for this place, else rate/hour (0 = OT rate)
        k = (day, cid, sid, kid)
        if k not in hm:
            hm[k] = None
            for f_, t_, hc, hd, hs, rt_ in hol:
                if f_ <= day <= t_ and (hc is None or hc == cid) and (hd is None or hd == sid) and (hs is None or hs == kid):
                    hm[k] = float(rt_ or 0)
                    break
        return hm[k]

    def is_wk(ds):
        if ds not in wkc:
            wkc[ds] = date.fromisoformat(ds).weekday() == we
        return wkc[ds]

    rows = []
    for r in e.itertuples(index=False):
        rws = by_emp.get(int(r.id))
        if not rws:
            continue
        cur = (_id(r.company_id), _id(r.dept_id), _id(r.sponsor_id))
        R, place, rtm = [], {}, {}
        for t in rws:   # (day, status, hours, ot, cid, sid, kid, weekend?, holiday rate or None, month key)
            cid = _id(t.company_id) if _id(t.company_id) is not None else cur[0]
            sid = _id(t.dept_id) if _id(t.dept_id) is not None else cur[1]
            kid = _id(t.sponsor_id) if _id(t.sponsor_id) is not None else cur[2]
            place[t.day] = (cid, sid, kid)
            R.append((t.day, t.status, 0.0 if _isna(t.hours) else float(t.hours), 0.0 if _isna(t.ot_hours) else float(t.ot_hours),
                      cid, sid, kid, is_wk(t.day), hrate(t.day, cid, sid, kid), "P" if cyc else t.day[:7]))
        nwf = lambda x: x[7] or x[8] is not None   # weekend or special holiday
        nonwork = lambda d: is_wk(d.isoformat()) or hrate(d.isoformat(), *place.get(d.isoformat(), cur)) is not None

        def rt(ds):   # monthly basic in force on that day
            if ds not in rtm:
                rtm[ds] = r.rate + inc_a * rate_steps(r.join_date, date.fromisoformat(ds), inc_y, inc_rep)
            return rtm[ds]

        bm = {}

        def bounds(mth):   # first day, last day, days, working days of the month (or of the whole pay period)
            if mth not in bm:
                if cyc:
                    lo, nd = D1, (D2 - D1).days + 1
                else:
                    y_, m_ = int(mth[:4]), int(mth[5:])
                    lo, nd = date(y_, m_, 1), calendar.monthrange(y_, m_)[1]
                bm[mth] = (lo, lo + timedelta(nd - 1), nd, max(sum(not nonwork(lo + timedelta(k)) for k in range(nd)), 1))
            return bm[mth]

        ad = adj_by.get(int(r.id), [])
        monthly = r.pay_type == "Monthly"
        full, gap, gap_used, pall, spa_used, mlast = set(), {}, set(), {}, set(), {}
        if monthly:
            for mth in sorted({x[9] for x in R}):
                lo, hi, nd, wd0 = bounds(mth)
                mr = [x for x in R if x[9] == mth]
                da, db = date.fromisoformat(min(x[0] for x in mr)), date.fromisoformat(max(x[0] for x in mr))
                mlast[mth] = max(x[0] for x in mr)
                span = sum(not nonwork(da + timedelta(k)) for k in range((db - da).days + 1))
                nk = [x for x in mr if not nwf(x)]
                gap[mth] = max(span - sum(1 for x in nk if x[1] in ("Present", "Leave", "Absent", "Off")), 0)
                pall[mth] = sum(1 for x in nk if x[1] in ("Present", "Leave"))
                if lo >= D1 and hi <= D2 and sum(1 for x in nk if x[1] == "Present") >= wd0:
                    full.add(mth)
        groups = {}
        for x in R:
            groups.setdefault((x[4], x[5], x[6]), []).append(x)
        first, otr_show, erows = True, 0.0, []
        for (cid, sid, kid) in sorted(groups, key=lambda k: tuple((v is None, v or 0) for v in k)):
            g = groups[(cid, sid, kid)]
            pres = [x for x in g if x[1] == "Present"]
            nor, wkd, hold = [x for x in pres if not nwf(x)], [x for x in pres if x[7] and x[8] is None], [x for x in pres if x[8] is not None]
            ot_h, reg_h = sum(x[3] for x in nor), sum(x[2] for x in nor)
            wk_h, hol_h = sum(x[2] + x[3] for x in wkd), sum(x[2] + x[3] for x in hold)
            basic = food = spa = oth = bonus = ot_pay = wk_pay = hol_pay = abs_ded = ex_pay = 0.0
            days_ab, days_nw, ex_days = sum(1 for x in g if x[1] == "Absent"), sum(1 for x in g if x[1] == "Off"), 0
            if monthly:
                days_ab = days_nw = 0
                ex_mode, ex_thr = ex_cfg.get(cid, ("Off", 10.0))
                for mth in sorted({x[9] for x in g}):
                    gm = [x for x in g if x[9] == mth]
                    lo, hi, nd, wdm = bounds(mth)
                    rate_m = rt(mlast[mth])
                    otr = otr_show = r.ot_rate if r.ot_rate > 0 else rate_m / wdm / std * otm
                    p_ = [x for x in gm if x[1] == "Present" and not nwf(x)]
                    l_ = [x for x in gm if x[1] == "Leave" and not nwf(x)]
                    w_ = [x for x in gm if x[1] == "Present" and x[7] and x[8] is None]
                    h_ = [x for x in gm if x[1] == "Present" and x[8] is not None]
                    paid = len(p_) + len(l_)
                    nwk = sum(1 for x in gm if x[1] == "Off" and not nwf(x))
                    ab = sum(1 for x in gm if x[1] == "Absent" and not nwf(x))
                    if mth not in gap_used:
                        ab += gap.get(mth, 0)
                        gap_used.add(mth)
                    days_ab += ab
                    days_nw += nwk
                    basic += (sum(rt(x[0]) for x in p_) + sum(rt(x[0]) for x in l_)) / wdm
                    basic += rate_m * ab * (1 / wdm - 1 / nd)   # an absent day's basic is cut at basic / days-of-month, not / working days
                    food += r.food_allow / wdm * (paid + nwk)
                    food += r.food_allow * ab * (1 / wdm - 1 / nd)   # absent day: food cut = food / days-of-month
                    if pall.get(mth):
                        spa += r.special_allow * paid / pall[mth]    # fixed amount, shared by days worked at each place
                    elif mth not in spa_used:
                        spa += r.special_allow
                        spa_used.add(mth)
                    oth += r.other_allow / wdm * (paid + nwk)
                    abs_ded += rate_m / nd * ab
                    if ex_mode != "Off" and ex_thr > 0:
                        exd = sum(1 for x in p_ if x[2] + x[3] > ex_thr)
                        ex_days += exd
                        ex_pay += rate_m / (ex_thr * nd) * exd
                    if not (ex_mode == "Instead of OT" and ex_thr > 0):
                        ot_pay += sum(x[3] for x in p_) * otr
                    wk_pay += sum(x[2] + x[3] for x in w_) * otr
                    hol_pay += sum((x[2] + x[3]) * (x[8] if x[8] > 0 else otr) for x in h_)
                    if mth in full:
                        bonus += rate_m / nd * len(p_) / wdm
            else:
                oe = otr_show = r.ot_rate if r.ot_rate > 0 else r.rate
                basic, ot_pay, wk_pay = reg_h * r.rate, ot_h * oe, wk_h * oe
                hol_pay = sum((x[2] + x[3]) * (x[8] if x[8] > 0 else oe) for x in hold)
            add = sum(a_ for k_, a_ in ad if k_ not in ("Advance", "Deduction")) if first else 0
            adv = sum(a_ for k_, a_ in ad if k_ == "Advance") if first else 0
            ded = sum(a_ for k_, a_ in ad if k_ == "Deduction") if first else 0
            first = False
            ded += basic * gp / 100 if str(r.nationality).strip().lower() == gn else 0
            net = basic + food + spa + oth + bonus + ot_pay + wk_pay + hol_pay + ex_pay + add - adv - abs_ded - ded
            tot_h = reg_h + ot_h + wk_h + hol_h
            erows.append({"Code": r.code, "Name": r.name, "Join Date": r.join_date, "Iqama ID": r.id_no or "",
                          "Passport No": r.passport_no or "", "Company": nm(cn, cid), "Section": nm(sn, sid),
                          "Sponsor": nm(kn, kid), "Labour": r.labour_type, "Pay": r.pay_type, "Mode": r.pay_mode,
                          "Monthly Basic Rate": rt(d2) if monthly else 0, "Hr Rate": 0 if monthly else r.rate,
                          "OT Rate": otr_show, "Days": len(pres), "Leave": sum(1 for x in g if x[1] == "Leave"),
                          "Absent": days_ab, "No Work": days_nw, "Normal Hrs": reg_h, "OT Hrs": ot_h, "Wknd Hrs": wk_h,
                          "Hol Hrs": hol_h, "Total Hrs": tot_h, "Basic": basic, "Food": food, "Special Allow": spa,
                          "Other Allow": oth, "OT Pay": ot_pay, "Wknd OT": wk_pay, "Hol Pay": hol_pay, "Ex Days": ex_days,
                          "Ex.hrs Pay": ex_pay, "Allowances": add, "Bonus": bonus, "Advance": adv, "Absent Ded": abs_ded,
                          "Deduction": ded, "Net": net, "Bank": net if r.pay_mode == "Bank" else 0,
                          "Cash": net if r.pay_mode != "Bank" else 0, "Invoice": tot_h * r.bill_rate})
        if merge and len(erows) > 1:   # transferred inside the period: one line, shown at the LAST workplace
            lastr = max(R, key=lambda x: x[0])
            m0 = dict(erows[0])
            for k_ in SUMC:
                m0[k_] = sum(x[k_] for x in erows)
            m0["Company"], m0["Section"], m0["Sponsor"] = nm(cn, lastr[4]), nm(sn, lastr[5]), nm(kn, lastr[6])
            erows = [m0]
        rows.extend(erows)
    df = pd.DataFrame(rows, columns=PCOLS).round(2)
    for col, v in (("Section", sec), ("Company", co), ("Sponsor", spn)):
        if v:
            df = df[df[col].isin(v)]
    return df


init_guard()
cur_ = S("currency")
LOGIN_CSS = """<style>
[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="collapsedControl"],[data-testid="stSidebarCollapsedControl"]{display:none}
.stApp{background:#f3f6fb}
.block-container{padding:0 !important;max-width:100% !important}
[data-testid="stHorizontalBlock"]{gap:0 !important}
.lg-left{min-height:100vh;box-sizing:border-box;padding:34px 56px;display:flex;flex-direction:column;justify-content:space-between;color:#fff;background:radial-gradient(circle at 88% 6%,rgba(255,255,255,.13) 0,rgba(255,255,255,0) 24%),radial-gradient(circle at 72% 60%,rgba(222,196,96,.30) 0,rgba(222,196,96,0) 16%),radial-gradient(circle at 6% 94%,rgba(70,110,210,.55) 0,rgba(70,110,210,0) 26%),linear-gradient(160deg,#0f2447 0%,#0f4c75 55%,#0e7c86 100%)}
.lg-left,.lg-left *{color:#fff !important}
.lg-brand{display:flex;align-items:center;gap:12px;font-size:17px}
.lg-logo{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:12px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);font-weight:800;font-size:15px}
.lg-mid h1{font-size:46px;line-height:1.08;font-weight:800;margin:0 0 18px;padding:0;letter-spacing:-.02em}
.lg-mid p{font-size:16px;line-height:1.6;max-width:470px;opacity:.9;margin:0 0 26px}
.lg-mid ul{list-style:none;padding:0;margin:0}
.lg-mid li{display:flex;align-items:center;gap:12px;margin:0 0 14px;font-size:15px}
.lg-mid li i{font-style:normal;width:26px;height:26px;border-radius:8px;background:rgba(255,255,255,.14);display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.lg-foot{font-size:12px;opacity:.75}
[data-testid="stColumn"]:nth-child(2)>[data-testid="stVerticalBlock"],[data-testid="column"]:nth-child(2)>div>[data-testid="stVerticalBlock"]{min-height:100vh;justify-content:center;padding:0 12%}
[data-testid="stForm"]{background:#fff;border:none !important;border-radius:22px;padding:34px 32px 26px;box-shadow:0 20px 50px rgba(30,60,120,.12)}
.lg-head{text-align:center;margin-bottom:10px}
.lg-head h2{margin:12px 0 2px;padding:0;font-size:26px;font-weight:800;color:#0f2447 !important}
.lg-head p{margin:0;color:#64748b !important;font-size:14px}
.lg-head .lg-logo.big{width:58px;height:58px;border-radius:16px;font-size:20px;background:linear-gradient(135deg,#14808f,#2c6db3);color:#fff !important;border:none}
[data-testid="stForm"] label p{font-size:11px !important;font-weight:700 !important;letter-spacing:.05em;text-transform:uppercase;color:#334155 !important}
[data-testid="stTextInputRootElement"]{border-radius:12px;background:#f8fafc;border:1px solid #dbe3ee}
[data-testid="stFormSubmitButton"] button{width:100%;height:48px;border:none;border-radius:12px;font-weight:700;background:linear-gradient(90deg,#14808f,#2c6db3);box-shadow:0 8px 18px rgba(30,110,170,.30)}
[data-testid="stFormSubmitButton"] button p{color:#fff !important}
</style>"""

if "user" not in st.session_state:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    nm_ = S("company")
    ini = ("".join(w[0] for w in nm_.split()[:2]) or "HR").upper()
    left, right = st.columns([1.15, 1], gap="small")
    left.markdown(
        f'<div class="lg-left"><div class="lg-brand"><span class="lg-logo">{html.escape(ini)}</span>'
        f'<b>{html.escape(nm_)}</b></div><div class="lg-mid"><h1>Your whole workforce,<br>one clear dashboard.</h1>'
        '<p>Attendance, leave, payroll and Iqama / ID dates for every company, section and kofil, '
        'always up to date and always in one place.</p><ul>'
        '<li><i>✓</i>Alerts before any Iqama / ID expires</li>'
        '<li><i>✓</i>Company, section and kofil wise reports</li>'
        '<li><i>✓</i>Custom date range on every page</li>'
        '<li><i>✓</i>Secure sign in with your own access level</li></ul></div>'
        f'<div class="lg-foot">© {html.escape(nm_)}</div></div>', unsafe_allow_html=True)
    with right:
        with st.form("login"):
            st.markdown(f'<div class="lg-head"><span class="lg-logo big">{html.escape(ini)}</span>'
                        '<h2>Welcome back</h2><p>Sign in to continue</p></div>', unsafe_allow_html=True)
            u = st.text_input("Username", placeholder="👤  your username")
            p_ = st.text_input("Password", type="password", placeholder="🔒  your password")
            if st.form_submit_button("Sign in", use_container_width=True):
                r_ = q("SELECT * FROM users WHERE lower(username)=lower(?) AND pw=?", (u.strip(), pw(p_)))
                if len(r_):
                    st.session_state.user, st.session_state.role = r_.username[0], r_.role[0]
                    st.rerun()
                else:
                    st.error("Wrong username or password")
        if q("SELECT COUNT(*) AS n FROM users WHERE username='admin' AND pw=?", (pw("admin123"),)).n[0]:
            st.caption("First login: admin / admin123 - change it in Users after signing in.")
        else:
            st.caption("Forgot your password? Ask your administrator to reset it.")
        with st.expander("Forgot username / password?"):
            try:
                rk = str(st.secrets.get("RECOVERY_KEY", ""))
            except Exception:
                rk = ""
            key_ = st.text_input("Recovery key", type="password", key="rk")
            if not rk:
                st.info('Recovery is not set up yet. In Streamlit: Manage app > Settings > Secrets, add  '
                        'RECOVERY_KEY = "your-long-secret"  and Save.')
            elif key_ and hmac.compare_digest(key_, rk):
                st.dataframe(q("SELECT username, role FROM users ORDER BY username"), hide_index=True)
                nu = st.text_input("Username (existing = reset password, new = create)", key="rku")
                npw = st.text_input("New password", type="password", key="rkp")
                nr = st.selectbox("Role", ["Admin", "HR", "Manager"], key="rkr")
                if st.button("Save login", key="rks") and nu.strip() and npw:
                    q("INSERT INTO users(username,pw,role) VALUES(?,?,?) ON CONFLICT(username) "
                      "DO UPDATE SET pw=excluded.pw, role=excluded.role", (nu.strip(), pw(npw), nr), fetch=False)
                    st.success("Saved. Now sign in with this username and password.")
            elif key_:
                st.error("Wrong recovery key")
    st.stop()
role = st.session_state.role
ALL = ["Dashboard", "Employees", "Transfer", "Setup", "Attendance", "Bulk Attendance", "Leave", "Adjustments", "Costs", "Payroll",
       "Invoices", "Commission", "Reports", "Settings"]
MENU = {"Admin": ALL + ["Users"], "HR": ALL, "Manager": ["Dashboard", "Attendance", "Bulk Attendance", "Leave", "Reports"]}[role]
def parse_perms(v):
    """'Attendance:VE|Leave:V' -> {'Attendance': 'VE', 'Leave': 'V'}  (V = show, E = edit, D = delete; no flags = role default)."""
    out = {}
    for part_ in str(v or "").split("|"):
        if part_:
            n_, sep_, f_ = part_.partition(":")
            out[n_] = f_ if sep_ else None
    return out


_pm = q("SELECT perms FROM users WHERE username=?", (st.session_state.user,))
_perm = parse_perms(_pm.perms[0]) if len(_pm) else {}
_restricted = st.session_state.user != "admin" and bool(_perm)     # the main 'admin' can never be locked out
if _restricted:          # this user has his own menu list (set by Admin in Settings > User access)
    MENU = [m_ for m_ in ALL if m_ in _perm] or ["Dashboard"]
MENU = [m_ for m_ in MENU if m_ != "Bulk Attendance" or S("bulk_on") == "Yes"]
st.sidebar.title(f"🏢 {S('company')}")
st.sidebar.write(f"👤 {st.session_state.user} ({role})")
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()
ICON = {"Dashboard": "🏠", "Employees": "👥", "Setup": "🏷️", "Attendance": "🗓️", "Leave": "🌴", "Adjustments": "➕",
        "Costs": "🧾", "Payroll": "💵", "Invoices": "📑", "Reports": "📊", "Transfer": "🔁", "Commission": "💰", "Bulk Attendance": "📆", "Settings": "⚙️", "Users": "🔑"}
page = st.sidebar.radio("Menu", MENU, format_func=lambda x: f"{ICON.get(x, '')}  {x}")
_pf = _perm.get(page) if _restricted else None
if _pf is None:                         # no personal setting: the role decides (Admin / HR edit, Admin delete)
    _CAN_E, _CAN_D = role in ("Admin", "HR"), role == "Admin"
    _RO["E"] = _RO["D"] = True          # old behaviour: nothing is blocked
else:                                   # personal setting for this menu
    _CAN_E, _CAN_D = "E" in _pf, "D" in _pf
    _RO["E"], _RO["D"] = _CAN_E, _CAN_D

# ---------------- Dashboard
def _import_employees():
    """Bulk import of employees (Excel / CSV) - shown inside the Employees menu."""
    T = ["Code", "Name", "Nationality", "ID No", "Passport No", "Phone", "Company", "Section", "Sponsor", "Labour Type", "Pay Type",
         "Pay Mode", "Rate", "Food Allow", "Special Allow", "Other Allow", "OT Rate", "Bill Rate", "Join Date", "ID Expiry"]
    st.download_button("⬇ Download template", pd.DataFrame(columns=T).to_csv(index=False), "employee_template.csv")
    st.caption("Labour Type: Company / Outside. Pay Type: Monthly / Hourly. Pay Mode: Bank / Cash. "
               "Companies, sections and sponsors are created automatically. Same Code = update.")
    up = st.file_uploader("Upload .xlsx or .csv", type=["xlsx", "csv"])
    if up is not None:
        df = pd.read_csv(up, dtype=str) if up.name.endswith(".csv") else pd.read_excel(up, dtype=str)
        st.dataframe(df.head(20), use_container_width=True)
        if st.button("Import now"):
            txt = lambda v: "" if pd.isna(v) else str(v).strip()
            num = lambda v: 0.0 if pd.isna(pd.to_numeric(v, errors="coerce")) else float(v)
            dt = lambda v: "" if pd.isna(pd.to_datetime(v, errors="coerce")) else str(pd.to_datetime(v).date())

            def idof(tbl, v):
                v = txt(v)
                if not v:
                    return None
                q(f"INSERT INTO {tbl}(name) VALUES(?) ON CONFLICT DO NOTHING", (v,), fetch=False)
                return int(q(f"SELECT id FROM {tbl} WHERE name=?", (v,)).id[0])

            n, rej = 0, []
            seen = {"c": {}, "i": {}, "p": {}}
            for _, r in df.iterrows():
                if not txt(r.get("Code")):
                    continue
                cd_, id_, ps_ = txt(r.get("Code")), txt(r.get("ID No")), txt(r.get("Passport No"))
                why = []
                for key_, val_, lab_ in (("c", cd_, "Code"), ("i", id_, "ID No"), ("p", ps_, "Passport No")):
                    if _nk(val_) and _nk(val_) in seen[key_]:
                        why.append(f"{lab_} '{val_}' is repeated inside the file (also {seen[key_][_nk(val_)]})")
                ex_ = q("SELECT id FROM employees WHERE UPPER(REPLACE(code,' ',''))=?", (_nk(cd_),))
                why += [m_ for m_ in emp_conflicts("", id_, ps_, skip_id=int(ex_.id[0]) if len(ex_) else None)]
                if why:
                    rej.append({"Code": cd_, "Name": txt(r.get("Name")), "Why rejected": "; ".join(why)})
                    continue
                for key_, val_ in (("c", cd_), ("i", id_), ("p", ps_)):
                    if _nk(val_):
                        seen[key_][_nk(val_)] = cd_
                save_emp(dict(code=txt(r.get("Code")), name=txt(r.get("Name")), nationality=txt(r.get("Nationality")),
                              id_no=txt(r.get("ID No")), passport_no=txt(r.get("Passport No")), phone=txt(r.get("Phone")), company_id=idof("companies", r.get("Company")),
                              dept_id=idof("departments", r.get("Section")), sponsor_id=idof("sponsors", r.get("Sponsor")),
                              labour_type=txt(r.get("Labour Type")) or "Company", pay_type=txt(r.get("Pay Type")) or "Monthly",
                              pay_mode=txt(r.get("Pay Mode")) or "Bank", rate=num(r.get("Rate")),
                              food_allow=num(r.get("Food Allow")), special_allow=num(r.get("Special Allow")), other_allow=num(r.get("Other Allow")), ot_rate=num(r.get("OT Rate")),
                              bill_rate=num(r.get("Bill Rate")), join_date=dt(r.get("Join Date")) or str(today()),
                              id_expiry=dt(r.get("ID Expiry"))))
                n += 1
            st.success(f"Imported / updated {n} employees")
            if rej:
                st.error(f"🚫 {len(rej)} row(s) NOT imported - duplicate Code / Iqama ID / Passport no.:")
                tbl(pd.DataFrame(rej), False)


@st.cache_data(ttl=600, show_spinner=False)
def _net_month(d1, d2):
    """Net payroll of one month (kept 10 minutes so the Dashboard opens fast)."""
    pdf = calc_payroll(d1, d2, [], [], [], [])
    return float(pdf.Net.sum()) if len(pdf) else 0.0


if page == "Dashboard":
    if S("marquee_on") == "Yes" and str(S("marquee_text")).strip():
      st.markdown(
        '<style>.mq{position:fixed;top:6px;left:0;right:170px;height:42px;overflow:hidden;white-space:nowrap;'
        'z-index:999990;pointer-events:none}'
        'body:has([data-testid="stSidebar"][aria-expanded="true"]) .mq{left:215px}'
        '.stApp:has([data-testid="stSidebar"][aria-expanded="true"]) .mq{left:215px}'
        '.mq span{display:inline-block;padding-left:100%;font-size:24px;line-height:42px;font-weight:800;color:#ff2e93;'
        'animation:mqmove 18s linear infinite}'
        '@keyframes mqmove{0%{transform:translateX(0)}100%{transform:translateX(-100%)}}</style>'
        f'<div class="mq"><span>{html.escape(str(S("marquee_text")))}</span></div>', unsafe_allow_html=True)
    st.header("Dashboard")
    show_dups()
    e = emp_df()
    t = str(today())
    m1 = today().replace(day=1)
    me = (m1.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    a = q("""SELECT a.status, COALESCE(a.hours,0) AS hours, COALESCE(a.ot_hours,0) AS ot_hours, e.name FROM attendance a JOIN employees e ON e.id=a.emp_id
        WHERE a.day=? AND e.active=1 ORDER BY a.id DESC""", (t,))
    n = len(e)
    pr, ab, lv = (int((a.status == x).sum()) for x in ("Present", "Absent", "Leave"))
    nm = max(n - pr - ab - lv, 0)

    def donut(parts, center, label):
        tot = sum(v for _, v, _ in parts)
        acc, stops = 0, []
        for _, v, col in parts:
            if v:
                stops.append(f"{col} {acc / tot * 100:.1f}% {(acc + v) / tot * 100:.1f}%")
                acc += v
        bg = ",".join(stops) or "#dfe8e1 0% 100%"
        leg = "".join(f'<div><span class="dot" style="background:{col}"></span>{nme}'
                      f'<b style="float:right">{v}</b></div>' for nme, v, col in parts)
        return (f'<div class="row"><div class="donut" style="background:conic-gradient({bg})"><div>'
                f'<b>{center}</b>{label}</div></div><div class="leg">{leg}</div></div>')

    n_co = int((e.labour_type == "Company").sum())
    n_out = int((e.labour_type == "Outside").sum())
    kp = [("👥", "Total Employees", n, "#e3f4e8"), ("🧍", "Present Today", pr, "#e3f4e8"),
          ("🌴", "On Leave", lv, "#fdf1d6"), ("🚫", "Absent", ab, "#fbe3df")]
    for col_, (ic, lb, v, bg) in zip(st.columns(4), kp):
        sub = (f'<div class="lb" style="margin-top:2px">Company labour: <b>{n_co}</b><br>Outside labour: <b>{n_out}</b></div>'
               if lb == "Total Employees" else "")
        col_.markdown(f'<div class="card kpi"><div class="ic" style="background:{bg}">{ic}</div>'
                      f'<div><div class="lb">{lb}</div><div class="v">{v}</div>{sub}</div></div>',
                      unsafe_allow_html=True)
    st.write("")
    c1, c2 = st.columns(2)
    c1.markdown('<div class="card"><div class="ttl">Attendance Overview</div>' + donut(
        [("Present", pr, "#2e7d4f"), ("Absent", ab, "#d64933"), ("On Leave", lv, "#f0b429"),
         ("Not marked", nm, "#cfd8d2")], pr, "Present") + "</div>", unsafe_allow_html=True)
    lvs = q("SELECT status FROM leaves WHERE start<=? AND \"end\">=?", (str(me), str(m1))).status
    L = lambda x: int((lvs == x).sum())
    c2.markdown('<div class="card"><div class="ttl">Leave Overview (this month)</div>' + donut(
        [("Approved", L("Approved"), "#2e7d4f"), ("Pending", L("Pending"), "#f0b429"),
         ("Rejected", L("Rejected"), "#d64933")], len(lvs), "Total") + "</div>", unsafe_allow_html=True)
    st.write("")
    vals = []
    for i in range(11, -1, -1):
        mm, yy = today().month - i, today().year
        while mm <= 0:
            mm, yy = mm + 12, yy - 1
        s0 = date(yy, mm, 1)
        e0 = (s0.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        vals.append((s0.strftime("%b %y"), _net_month(str(s0), str(e0))))
    mx = max(v for _, v in vals) or 1
    bars = "".join(f'<div><small style="font-size:10px;font-weight:700;color:#ff2e93;white-space:nowrap">{v:,.0f}</small><span style="height:{v / mx * 70:.0f}%"></span>{l}</div>'
                   for l, v in vals)
    st.markdown(f'<div class="card"><div class="ttl">Monthly Payroll Summary (last 12 months)</div>'
                f'<small>Net payroll this month</small>'
                f'<div style="font-size:26px;font-weight:700">{vals[-1][1]:,.0f} {cur_}</div>'
                f'<div class="bars">{bars}</div></div>', unsafe_allow_html=True)
    st.write("")
    if len(e):
        e["days_left"] = (pd.to_datetime(e.id_expiry, errors="coerce") - pd.Timestamp(today())).dt.days
        ex = e[e.days_left <= 60][["code", "name", "section", "sponsor", "id_expiry", "days_left"]]
        if len(ex):
            st.subheader("⚠ ID / Iqama expired or expiring within 60 days")
            tbl(ex.sort_values("days_left"), False)

# ---------------- Employees
elif page == "Employees":
    st.header("Employees / Labour")
    show_dups()
    if st.session_state.get("flash_emp"):
        st.success(st.session_state.pop("flash_emp"))
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    pick = lambda t, n: None if n == "-" else int(t[t.name == n].id.iloc[0])
    v = st.session_state.get("empv", 0)
    with st.expander("➕ Add employee  (Code, Iqama ID and Passport no. must be unique)"):
        c = st.columns(4)
        code, name = c[0].text_input("Code", key=f"e1{v}"), c[1].text_input("Name", key=f"e2{v}")
        nat, idn = c[2].text_input("Nationality", key=f"e3{v}"), c[3].text_input("ID / Iqama no.", key=f"e4{v}")
        c = st.columns(4)
        pas = c[0].text_input("Passport no.", key=f"e5{v}")
        co = c[1].selectbox("Client company", ["-"] + cm.name.tolist(), key=f"e6{v}")
        sec = c[2].selectbox("Section", ["-"] + ds.name.tolist(), key=f"e7{v}")
        spn = c[3].selectbox("Sponsor / Kofil", ["-"] + sp.name.tolist(), key=f"e8{v}")
        c = st.columns(4)
        lt = c[0].selectbox("Labour type", ["Company", "Outside"], key=f"e9{v}")
        pt = c[1].selectbox("Pay type", ["Monthly", "Hourly"], key=f"e10{v}")
        pm = c[2].selectbox("Pay mode", ["Bank", "Cash"], key=f"e11{v}")
        rate = c[3].number_input("Normal hour rate (per hour)" if pt == "Hourly" else "Monthly basic salary", 0.0,
                                 key=f"e12{v}{pt}")
        hr_, sfx = pt == "Hourly", (" (monthly staff only)" if pt == "Hourly" else "")
        c = st.columns(4)
        food = c[0].number_input("Food allowance / month" + sfx, 0.0, key=f"e13{v}", disabled=hr_)
        spa = c[1].number_input("Special allowance / month" + sfx, 0.0, key=f"e19{v}", disabled=hr_)
        oth = c[2].number_input("Other allowance / month" + sfx, 0.0, key=f"e20{v}", disabled=hr_)
        otr = c[3].number_input("OT rate / hour (0 = auto)", 0.0, key=f"e14{v}")
        c = st.columns(4)
        bill = c[0].number_input("Bill rate / hour (client invoice)", 0.0, key=f"e15{v}")
        ph, jd = c[1].text_input("Phone", key=f"e16{v}"), c[2].date_input("Join date", today(), key=f"e17{v}")
        exp = c[3].date_input("ID expiry", today() + timedelta(days=365), key=f"e18{v}")
        if st.button("💾 Save employee", key=f"esave{v}") and code and name:
            bad_ = emp_conflicts(code, idn, pas)
            for m_ in bad_:
                st.error("🚫 DUPLICATE - not saved: " + m_ + ". To change that person use Edit below.")
            if not bad_:
                save_emp(dict(code=code, name=name, nationality=nat, id_no=idn, passport_no=pas, company_id=pick(cm, co),
                              dept_id=pick(ds, sec), sponsor_id=pick(sp, spn), labour_type=lt, pay_type=pt, pay_mode=pm,
                              rate=rate, food_allow=0.0 if hr_ else food, special_allow=0.0 if hr_ else spa,
                              other_allow=0.0 if hr_ else oth, ot_rate=otr, bill_rate=bill, phone=ph,
                              join_date=str(jd), id_expiry=str(exp)))
                st.session_state["empv"], st.session_state["flash_emp"] = v + 1, f"Saved {code}"
                st.rerun()
    with st.expander("📥 Bulk import employees (Excel / CSV)"):
        _import_employees()
    showall = st.checkbox("Show deactivated employees too", key="emp_all")
    f = filters("emp")
    df = apply_f(emp_df(None if showall else True), *f[2:]).drop(columns=["id", "company_id", "dept_id", "sponsor_id"])
    df["status"] = df.active.map({1: "Active", 0: "Deactivated"})
    df["monthly_basic_rate"], df["hr_rate"] = df.rate.where(df.pay_type == "Monthly", 0), df.rate.where(df.pay_type == "Hourly", 0)
    df["current_basic"] = [eff_rate(r_, j_, today()) if p_ == "Monthly" else 0 for r_, j_, p_ in zip(df.rate, df.join_date, df.pay_type)]
    df = df.rename(columns={"id_no": "iqama_id"})[["code", "name", "status", "join_date", "iqama_id", "passport_no", "company", "section",
                                                   "sponsor", "labour_type", "pay_type", "pay_mode", "monthly_basic_rate", "current_basic",
                                                   "hr_rate", "ot_rate", "food_allow", "special_allow", "other_allow",
                                                   "bill_rate", "nationality", "phone", "id_expiry"]]
    tbl(df)
    download(df, "employees", hdr_of(*f[:7]))
    if len(df):
        x = st.selectbox("Deactivate employee", df.code + " - " + df["name"])
        if st.button("Deactivate"):
            q("UPDATE employees SET active=0 WHERE code=?", (x.split(" - ")[0],), fetch=False); st.rerun()
        st.caption("Deactivated staff keep all history and reports but no longer appear in the running attendance sheet and lists.")
    inact = emp_df(False)
    if len(inact):
        y = st.selectbox("Reactivate employee", ["—"] + (inact.code + " - " + inact["name"]).tolist(), key="emp_re")
        if y != "—" and st.button("Reactivate", key="emp_re_b"):
            q("UPDATE employees SET active=1 WHERE code=?", (y.split(" - ")[0],), fetch=False); st.rerun()

# ---------------- Transfer
elif page == "Transfer":
    st.header("Transfer: Company / Section / Kofil")
    if st.session_state.get("flash_trf"):
        st.success(st.session_state.pop("flash_trf"))
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    idof = lambda t, n: None if n.startswith("—") else int(t[t.name == n].id.iloc[0])
    t1, t2, t3 = st.tabs(["➕ New transfer", "📜 Transfer history", "📄 Employee document"])
    with t1:
        f = filters("trn")
        allr = emp_df()
        e = apply_f(allr, *f[2:])
        opts = [f"{r.code} - {r['name']}  ({r.company or '-'} / {r.section or '-'} / {r.sponsor or '-'})" for _, r in e.iterrows()]
        tv = st.session_state.get("trfv", 0)
        sel = st.multiselect("Employees to transfer (use the filters above to narrow the list)", opts, key=f"trf_e{tv}")
        c = st.columns(4)
        day = c[0].date_input("Effective date", today(), key=f"trf_d{tv}")
        nco = c[1].selectbox("New company", ["— no change"] + cm.name.tolist(), key=f"trf_c{tv}")
        nse = c[2].selectbox("New section", ["— no change"] + ds.name.tolist(), key=f"trf_s{tv}")
        nsp = c[3].selectbox("New Sponsor / Kofil", ["— no change"] + sp.name.tolist(), key=f"trf_k{tv}")
        note = st.text_input("Note (reason / letter no.)", key=f"trf_n{tv}")
        upd = st.checkbox("Also move attendance already saved from the effective date onward", True, key=f"trf_u{tv}")
        if st.button("🔁 Transfer selected employees", key=f"trf_go{tv}"):
            co_, se_, sp_ = idof(cm, nco), idof(ds, nse), idof(sp, nsp)
            if not sel:
                st.warning("Select at least one employee.")
            elif co_ is None and se_ is None and sp_ is None:
                st.warning("Choose a new company, section or kofil.")
            else:
                for s_ in sel:
                    do_transfer(allr[allr.code == s_.split(" - ")[0]].iloc[0], co_, se_, sp_, day, note, upd)
                st.session_state["trfv"], st.session_state["flash_trf"] = tv + 1, f"Transferred {len(sel)} employee(s)"
                st.rerun()
    with t2:
        f = filters("trh")
        df = trf_df(f[0], f[1], f[2:]).drop(columns=["id"])
        tbl(df)
        download(df, "transfer_history", hdr_of(*f[:7]))
        st.caption("Edit or delete a history line in the section at the bottom of this page.")
    with t3:
        allr = emp_df()
        who = st.selectbox("Employee", ["—"] + (allr.code + " - " + allr["name"]).tolist(), key="trf_who")
        if who != "—":
            r = allr[allr.code == who.split(" - ")[0]].iloc[0]
            ev, wk = emp_history(r)
            prof = pd.DataFrame([{"Code": r.code, "Name": r["name"], "Iqama ID": r.id_no or "", "Passport No": r.passport_no or "",
                                  "Nationality": r.nationality, "Join date": r.join_date, "Pay type": r.pay_type,
                                  "Labour": r.labour_type, "Current company": r.company or "-",
                                  "Current section": r.section or "-", "Current kofil": r.sponsor or "-"}])
            st.subheader("Profile")
            tbl(prof, False)
            st.subheader("Joined / transfers")
            tbl(ev, False)
            st.subheader("Where he worked (from attendance)")
            tbl(wk)
            try:
                st.download_button("🖨 Employee document PDF (print)",
                                   doc_pdf(f"Employee document - {r.code} {r['name']}", f"Printed {today()}",
                                           [("Profile", prof), ("Joined / transfers", ev),
                                            ("Where he worked (company / section / kofil)", add_total(wk))],
                                           appr=approvers(Hdr(""), pd.DataFrame({"Sponsor": [r.sponsor or ""]}))),
                                   f"employee_{r.code}.pdf", "application/pdf", key="trf_pdf")
            except ImportError:
                st.caption("pip install reportlab")

# ---------------- Commission
elif page == "Commission":
    st.header("Commission")
    if st.session_state.get("flash_com"):
        st.success(st.session_state.pop("flash_com"))
    t1, t2 = st.tabs(["➕ Persons & rates", "📊 Commission report"])
    with t1:
        st.caption("Commission = total hours worked by ALL labour under the chosen Company / Section / Sponsor-Kofil "
                   "(All = no limit) x the rate per hour. Add one line per person and scope; edit or delete lines at the "
                   "bottom of this page. Lines of the same person that overlap are added twice, so keep them separate.")
        cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
        cv = st.session_state.get("comv", 0)
        c = st.columns(4)
        person, phone = c[0].text_input("Person name", key=f"cm1{cv}"), c[1].text_input("Phone", key=f"cm2{cv}")
        crate, cnote = c[2].number_input("Commission rate per hour", 0.0, key=f"cm3{cv}"), c[3].text_input("Note", key=f"cm4{cv}")
        c = st.columns(4)
        sco = c[0].selectbox("Company", ["All"] + cm.name.tolist(), key=f"cm5{cv}")
        sse = c[1].selectbox("Section", ["All"] + ds.name.tolist(), key=f"cm6{cv}")
        ssp = c[2].selectbox("Sponsor / Kofil", ["All"] + sp.name.tolist(), key=f"cm7{cv}")
        if c[3].button("➕ Add commission line", key=f"cm_add{cv}") and person.strip():
            idf = lambda t, n: None if n == "All" else int(t[t.name == n].id.iloc[0])
            q("INSERT INTO commissions(person,phone,company_id,dept_id,sponsor_id,rate,note,active) VALUES(?,?,?,?,?,?,?,1)",
              (person.strip(), phone, idf(cm, sco), idf(ds, sse), idf(sp, ssp), float(crate), cnote), fetch=False)
            st.session_state["comv"], st.session_state["flash_com"] = cv + 1, f"Added {person.strip()}"
            st.rerun()
        tbl(q("""SELECT k.id, k.person, k.phone, c.name AS company, d.name AS section, s.name AS sponsor, k.rate, k.note, k.active
            FROM commissions k LEFT JOIN companies c ON c.id=k.company_id LEFT JOIN departments d ON d.id=k.dept_id
            LEFT JOIN sponsors s ON s.id=k.sponsor_id ORDER BY k.person"""), False)
    with t2:
        f = pay_filters("com")
        rules = q("""SELECT k.id, k.person, k.phone, c.name AS company, d.name AS section, s.name AS sponsor, k.rate, k.note, k.active
            FROM commissions k LEFT JOIN companies c ON c.id=k.company_id LEFT JOIN departments d ON d.id=k.dept_id
            LEFT JOIN sponsors s ON s.id=k.sponsor_id WHERE k.active=1 ORDER BY k.person""")
        shown = False
        for gi, (a, b, cs) in enumerate(st.session_state["_grp_com"]):
            p = calc_payroll(a, b, f[2], f[3], f[4], f[5], cs, f[7], st.session_state["_cyc_com"], False)
            if p.empty or rules.empty:
                continue
            rows = []
            for _, k in rules.iterrows():
                m = p
                for col, val in (("Company", k.company), ("Section", k.section), ("Sponsor", k.sponsor)):
                    if val:
                        m = m[m[col] == val]
                if m.empty:
                    continue
                hrs = float(m["Total Hrs"].sum())
                rows.append({"Person": k.person, "Company": k.company or "All", "Section": k.section or "All",
                             "Kofil": k.sponsor or "All", "Labour": int(m.Code.nunique()), "Total Hrs": round(hrs, 2),
                             "Rate/hr": k.rate, "Commission": round(hrs * k.rate, 2)})
            if not rows:
                continue
            shown = True
            df = pd.DataFrame(rows)
            st.subheader(f"Period {dmy(a)} to {dmy(b)}  -  {', '.join(cs) if cs else 'All companies'}")
            tbl(df)
            st.markdown("**Commission per person**")
            tbl(df.groupby("Person", as_index=False).agg(**{"Total Hrs": ("Total Hrs", "sum"), "Commission": ("Commission", "sum")}))
            download(df, "commission", hdr_of(a, b, f[2], f[3], f[4], f[5], cs), str(gi))
        if not shown:
            st.info("No commission in this period (add lines first, and make sure attendance is marked).")

# ---------------- Setup
elif page == "Setup":
    st.header("Setup: Client companies, Sections, Sponsors / Kofil")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Client companies")
        n, v = st.text_input("Company name"), st.text_input("VAT / Tax no")
        cdy = st.number_input("Pay cycle start day (1 = whole month, 21 = 21st to 20th)", 1, 28, 1)
        exm = st.selectbox("Extra-hour pay (a day over N hours pays 1 hour of basic)", ["Off", "Instead of OT", "Plus OT"])
        exh = st.number_input("... N = hours per day", 1.0, 24.0, 10.0)
        if st.button("Add company") and n:
            q("INSERT INTO companies(name,vat,cycle_day,exh_mode,exh_hours) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING", (n, v, int(cdy), exm, float(exh)), fetch=False); st.rerun()
        tbl(q("SELECT name, vat, cycle_day, exh_mode, exh_hours FROM companies"), False)
    with c2:
        st.subheader("Sections")
        n = st.text_input("New section")
        if st.button("Add section") and n:
            q("INSERT INTO departments(name) VALUES(?) ON CONFLICT DO NOTHING", (n,), fetch=False); st.rerun()
        tbl(q("SELECT name FROM departments"), False)
    with c3:
        st.subheader("Sponsors / Kofil")
        n, p_ = st.text_input("Sponsor / Kofil name"), st.text_input("Phone")
        apb = st.text_input("Approved by (name printed at the bottom right of this kofil's documents)")
        if st.button("Add sponsor") and n:
            q("INSERT INTO sponsors(name,phone,approved_by) VALUES(?,?,?) ON CONFLICT DO NOTHING", (n, p_, apb), fetch=False); st.rerun()
        tbl(q("SELECT name, phone, approved_by FROM sponsors"), False)

# ---------------- Attendance
elif page == "Attendance":
    st.header("Attendance: P / A / L, normal hours & OT hours")
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    cn, sn = dict(zip(cm.id, cm.name)), dict(zip(ds.id, ds.name))
    ci, si = {v: int(k) for k, v in cn.items()}, {v: int(k) for k, v in sn.items()}
    cl, sl, kl = list(cn.values()), list(sn.values()), sp.name.tolist()
    kn = dict(zip(sp.id, sp.name))
    ki = {v: int(k) for k, v in kn.items()}
    c = st.columns([1, 1.2, 1.2, 1.2, 1.1, 0.9, 0.9])
    day = dbox(c[0], "Date", today(), "att_d")
    with c[1]:
        fco = msel("Company *", cl, "att_co", False, "Select (required)")
    with c[2]:
        fsec = msel("Section *", sl, "att_sec", False, "Select (required)")
    with c[3]:
        fspn = msel("Sponsor / Kofil *", kl, "att_spn", False, "Select (required)")
    with c[4]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        pick = st.selectbox("Set status for ALL", ["—"] + list(LBL.values()), key="att_st")
    with c[5]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        hn_pick = st.selectbox("Normal hrs for ALL", ["—", 8, 10, 12], key="att_hn", help="'—' = default from Settings")
    with c[6]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        ho_pick = st.selectbox("OT hrs for ALL", ["—", 0, 1, 2], key="att_ho", help="'—' = default from Settings")
    qs = search_box("🔎 Search name / code / Iqama / passport", "att_q")
    if not (fco and fsec and fspn):
        st.warning("Company, Section and Sponsor / Kofil are mandatory. Select them (or choose 'All') "
                   "to open the attendance sheet.")
    else:
        e = apply_f(emp_df(), eff(fsec, sl), (), (), eff(fspn, kl), eff(fco, cl), qs)
        old = q("SELECT * FROM attendance WHERE day=?", (str(day),))
        dn, do_ = float(S("def_normal")), float(S("def_ot"))
        wkend = day.weekday() == int(S("weekend"))
        hol, hflag = q("SELECT * FROM holidays"), False
        nm = lambda v, d: d.get(int(v), "") if pd.notna(v) else ""
        rows = []
        for _, r in e.iterrows():
            o = old[old.emp_id == r.id]
            h = o.iloc[0] if len(o) else None
            cur = CODE.get(h["status"], "P") if h is not None else None
            g = lambda col, dflt: h[col] if h is not None and pd.notna(h[col]) else dflt
            is_h = hol_rate(hol, str(day), r.company_id, r.dept_id, r.sponsor_id) is not None
            hflag = hflag or is_h
            stt = pick[-1] if pick != "—" else (cur or ("O" if (wkend or is_h) else "P"))
            sv = cur == "P" and stt == "P"
            nh, oh = (float(g("hours", dn)), float(g("ot_hours", 0.0))) if sv else (dn, do_)
            if stt == "P":
                nh = float(hn_pick) if hn_pick != "—" else nh
                oh = float(ho_pick) if ho_pick != "—" else oh
            rows.append({"id": r.id, "Code": r.code, "Name": r["name"], "Iqama ID": r.id_no or "",
                         "Passport No": r.passport_no or "", "Pay Type": r.pay_type, "Labour": r.labour_type,
                         "Sponsor": nm(g("sponsor_id", None), kn) or (r.sponsor or ""), "Company": nm(g("company_id", None), cn) or (r.company or ""),
                         "Section": nm(g("dept_id", None), sn) or (r.section or ""),
                         "OT Rate": ot_rate_of(r.rate, r.pay_type, r.ot_rate, str(day), r.join_date), "Status": LBL[stt],
                         "Normal Hrs": nh, "OT Hrs": oh, "Total Hrs": nh + oh if stt == "P" else 0.0})
        if wkend:
            st.info("This date is the weekend day: everyone starts as O (no work, no pay). Change to P only for those "
                    "who worked - all their hours are then paid as OT.")
        if hflag:
            st.info("Special holiday today for some of these staff: they start as O (no work, no pay). Mark P only for "
                    "those who worked - all their hours are paid at the holiday rate (or their OT rate).")
        ed = st.data_editor(pd.DataFrame(rows).pipe(lambda d: d.insert(0, "S/L", range(1, len(d) + 1)) or d), hide_index=True, use_container_width=True,
                            key=f"att{day}{fco}{fsec}{fspn}{pick}{hn_pick}{ho_pick}{qs}",
                            disabled=["S/L", "id", "Code", "Name", "Iqama ID", "Passport No", "Pay Type", "Labour", "Sponsor",
                                      "OT Rate", "Total Hrs"],
                            column_config={"id": None,
                                           "Company": st.column_config.SelectboxColumn(options=[""] + cl),
                                           "Section": st.column_config.SelectboxColumn(options=[""] + sl),
                                           "Status": st.column_config.SelectboxColumn(options=list(LBL.values()),
                                                                                      help="P=Present, A=Absent, L=Leave, O=No work"),
                                           "Normal Hrs": st.column_config.NumberColumn(min_value=0.0, max_value=24.0, step=0.5),
                                           "OT Hrs": st.column_config.NumberColumn(min_value=0.0, max_value=16.0, step=0.5)})
        if len(ed):
            sc = ed.Status.str[-1]
            isp = sc == "P"
            nh_, oh_ = ed["Normal Hrs"].where(isp, 0.0), ed["OT Hrs"].where(isp, 0.0)
            tbl(pd.DataFrame([{"TOTAL": f"TOTAL ({len(ed)} staff)", "P": int(isp.sum()), "A": int((sc == "A").sum()),
                                        "L": int((sc == "L").sum()), "O": int((sc == "O").sum()),
                                        "Normal Hrs": round(nh_.sum(), 2), "OT Hrs": round(oh_.sum(), 2),
                                        "Total Hrs": round((nh_ + oh_).sum(), 2)}]), False)
            sheet = sign(ed.drop(columns=["id"]).assign(Status=sc, **{"Normal Hrs": nh_, "OT Hrs": oh_, "Total Hrs": nh_ + oh_}))
            st.session_state["_monlab"] = f"Attendance date: {day.strftime('%d/%m/%Y')}"
            download(sheet, f"attendance_{day}", hdr_of(str(day), str(day), eff(fsec, sl), (), (), eff(fspn, kl), eff(fco, cl)), "att")
        st.caption("🟢 P = Present (paid), 🟡 L = Leave (paid), 🔴 A = Absent (basic / days-of-month cut twice: from basic + penalty), ⚪ O = No work (that day's basic is not paid; no penalty, food kept). "
                   "'Set status for ALL' fills every row with the chosen status - then change single rows if needed. "
                   "Normal / OT hours are pre-filled from Settings (default 10 + 2). Total Hrs updates after Save. "
                   "Weekend day: no work = no pay, work = all hours paid as OT.")
        if st.button("💾 Save attendance"):
            for _, r in ed.iterrows():
                code = r.Status[-1]
                pr_ = code == "P"
                q("INSERT INTO attendance(emp_id,day,status,hours,ot_hours,company_id,dept_id,sponsor_id) VALUES(?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(emp_id,day) DO UPDATE SET status=excluded.status,hours=excluded.hours,"
                  "ot_hours=excluded.ot_hours,company_id=excluded.company_id,dept_id=excluded.dept_id,sponsor_id=excluded.sponsor_id",
                  (int(r.id), str(day), REV[code], float(r["Normal Hrs"]) if pr_ else 0.0,
                   float(r["OT Hrs"]) if pr_ else 0.0, ci.get(r.Company), si.get(r.Section), ki.get(r.Sponsor)), fetch=False)
            st.success("Saved")

# ---------------- Bulk Attendance
elif page == "Bulk Attendance":
    st.header("Bulk attendance: many days in one entry")
    st.caption("For when you do not enter attendance every day. Choose the period and Company / Section / Kofil, then change only "
               "the exceptions (A, L, O). Working days start as P with the default hours (Settings); Fridays, special holidays "
               "start as O (saved too); any date, past or future, can be saved. Saved records are shown as they are and are kept unless you change the cell. "
               "A blank cell writes nothing. To delete a record use Attendance > Edit / Delete.")
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    cl, sl, kl = cm.name.tolist(), ds.name.tolist(), sp.name.tolist()
    c = st.columns([1, 1, 1.2, 1.2, 1.2, 1.1, 0.9, 0.9])
    d1 = dbox(c[0], "From", today().replace(day=1), "bk_a")
    d2 = dbox(c[1], "To", today(), "bk_b")
    with c[2]:
        fco = msel("Company *", cl, "bk_co", False, "Select (required)")
    with c[3]:
        fsec = msel("Section *", sl, "bk_sec", False, "Select (required)")
    with c[4]:
        fspn = msel("Sponsor / Kofil *", kl, "bk_spn", False, "Select (required)")
    with c[5]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        bpick = st.selectbox("Set status for ALL", ["—", "P", "A", "L", "O"], key="bk_st",
                             help="Fills every cell in the grid with this status (Fridays / holidays too - those who work then are paid by the weekend / holiday rules). "
                                  "Then change single cells if needed.")
    with c[6]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        bhn = st.selectbox("Normal hrs for ALL", ["—", 8, 10, 12], key="bk_hn", help="'—' = default from Settings")
    with c[7]:
        st.markdown('<span class="cb cb-st"></span>', unsafe_allow_html=True)
        bho = st.selectbox("OT hrs for ALL", ["—", 0, 1, 2], key="bk_ho", help="'—' = default from Settings")
    qs = search_box("🔎 Search name / code / Iqama / passport", "bk_q")
    if not (fco and fsec and fspn):
        st.warning("Company, Section and Sponsor / Kofil are mandatory. Select them (or choose 'All') to open the grid.")
    elif d2 < d1 or (d2 - d1).days > 61:
        st.error("Choose a period of 1 to 62 days (From must not be after To).")
    else:
        e = apply_f(emp_df(), eff(fsec, sl), (), (), eff(fspn, kl), eff(fco, cl), qs)
        if len(e) > 400:
            st.warning(f"{len(e)} staff are too many for one grid (maximum 400). Narrow it with Company / Section / Kofil or the search box.")
        elif e.empty:
            st.info("No staff found.")
        else:
            if st.session_state.get("bk_msg"):
                st.success(st.session_state.pop("bk_msg"))
            orig, days, labs, exk, tr = bulk_build(e, d1, d2)
            grid = orig.copy()
            if bpick != "—":
                grid[labs] = bpick      # shown / edited values; "orig" stays what is really saved, so saved cells that differ are rewritten
            grid.insert(0, "S/L", range(1, len(grid) + 1))
            if bhn != "—":
                grid["Normal Hrs/day"] = float(bhn)
            if bho != "—":
                grid["OT Hrs/day"] = float(bho)
            ed = st.data_editor(grid, hide_index=True, use_container_width=True, key=f"bulk{d1}{d2}{fco}{fsec}{fspn}{qs}{bpick}{bhn}{bho}",
                                disabled=["S/L", "id", "Code", "Name", "Iqama ID", "Pay Type", "Company", "Section", "Sponsor"],
                                column_config={"id": None, **{lab: _selcol() for lab in labs}})
            ed = ed.drop(columns=["S/L"])
            tot = {f"{k} days": int((ed[labs] == k).sum().sum()) for k in "PALO"}
            tbl(pd.DataFrame([{"TOTAL": f"TOTAL ({len(ed)} staff)", **tot}]), False)
            rows = bulk_rows(orig, ed, days, labs, exk, tr, e, bhn != "—" or bho != "—")
            n_new = sum(1 for r_ in rows if (r_[0], r_[1]) not in exk)
            if not rows:
                st.warning(f"Nothing to save: {len(exk)} day records in this period are ALREADY saved and nothing was changed. "
                           "Change a cell (or use 'Set status for ALL' with a different status) to save new values.")
            st.info(f"Ready to save: {n_new} new day records and {len(rows) - n_new} changed ones "
                    f"({d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}). Normal / OT hours per day come from the two "
                    "columns on the left of the days (change them per person if different).")
            if st.button("💾 Save bulk attendance", key="bk_save") and rows:
                q_many(BULK_SQL, rows)
                st.session_state["bk_msg"] = (f"✅ Saved {len(rows)} day records "
                                              f"({d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}).")
                st.rerun()
            sheet = ed.drop(columns=["id"]).copy()
            for k in "PALO":
                sheet[k] = (ed[labs] == k).sum(axis=1)
            st.session_state["_monlab"] = f"Attendance {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}"
            download(sheet, "bulk_attendance", hdr_of(str(d1), str(d2), eff(fsec, sl), (), (), eff(fspn, kl), eff(fco, cl)), "bk")

# ---------------- Leave
elif page == "Leave":
    st.header("Leave")
    e = emp_df()
    with st.expander("➕ New leave request"):
        with st.form("lv"):
            x = st.selectbox("Employee", e.code + " - " + e["name"])
            lt = st.selectbox("Type", ["Annual", "Sick", "Emergency", "Unpaid", "Other"])
            a, b = st.date_input("From", today()), st.date_input("To", today())
            if st.form_submit_button("Submit"):
                eid = int(e[e.code == x.split(" - ")[0]].id.iloc[0])
                q("INSERT INTO leaves(emp_id,ltype,start,\"end\",days,status) VALUES(?,?,?,?,?,'Pending')",
                  (eid, lt, str(a), str(b), (b - a).days + 1), fetch=False); st.rerun()
    d1, d2, sec, lt, pt, spn, co, qs = filters("lv")
    df = q("""SELECT l.id, e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type, e.pay_type,
        l.ltype, l.start, l.\"end\", l.days, l.status FROM leaves l JOIN employees e ON e.id=l.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id LEFT JOIN companies c ON c.id=e.company_id
        WHERE l.start<=? AND l.\"end\">=?""", (d2, d1))
    df = apply_f(df, sec, lt, pt, spn, co, qs)
    tbl(df); download(df, "leave", hdr_of(d1, d2, sec, lt, pt, spn, co))
    pend = df[df.status == "Pending"]
    if len(pend):
        i = st.selectbox("Pending request ID", pend.id)
        c = st.columns(2)
        if c[0].button("✅ Approve"):
            r = q("SELECT * FROM leaves WHERE id=?", (int(i),)).iloc[0]
            s = datetime.strptime(r.start, "%Y-%m-%d").date()
            for k in range(int(r.days)):
                q("INSERT INTO attendance(emp_id,day,status,hours) VALUES(?,?,?,0) ON CONFLICT(emp_id,day) "
                  "DO UPDATE SET status=?", (int(r.emp_id), str(s + timedelta(k)),
                  "Absent" if r.ltype == "Unpaid" else "Leave", "Absent" if r.ltype == "Unpaid" else "Leave"),
                  fetch=False)
            q("UPDATE leaves SET status='Approved' WHERE id=?", (int(i),), fetch=False); st.rerun()
        if c[1].button("❌ Reject"):
            q("UPDATE leaves SET status='Rejected' WHERE id=?", (int(i),), fetch=False); st.rerun()

# ---------------- Adjustments
elif page == "Adjustments":
    st.header("Advances, Deductions, Bonus & Allowance")
    e = emp_df()
    with st.form("adj"):
        c = st.columns(5)
        x = c[0].selectbox("Employee", e.code + " - " + e["name"])
        k = c[1].selectbox("Type", ["Advance", "Deduction", "Bonus", "Allowance", "Supervisor/Operator", "Foundation Day", "Skill/Villa", "Extra", "Eid Bonus"])
        am = c[2].number_input("Amount", 0.0)
        dy = c[3].date_input("Date", today())
        nt = c[4].text_input("Note")
        if st.form_submit_button("Add"):
            eid = int(e[e.code == x.split(" - ")[0]].id.iloc[0])
            q("INSERT INTO adjustments(emp_id,day,kind,amount,note) VALUES(?,?,?,?,?)",
              (eid, str(dy), k, am, nt), fetch=False)
            st.rerun()
    f = filters("adj")
    df = q("""SELECT a.id, a.day, e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, a.kind, a.amount, a.note FROM adjustments a JOIN employees e ON e.id=a.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id LEFT JOIN companies c ON c.id=e.company_id
        WHERE a.day BETWEEN ? AND ?""", (f[0], f[1]))
    df = apply_f(df, *f[2:])
    tbl(df)
    download(df, "adjustments", hdr_of(*f[:7]))
    rid = st.number_input("Delete entry ID", 0, step=1)
    if st.button("Delete entry") and rid:
        q("DELETE FROM adjustments WHERE id=?", (int(rid),), fetch=False)
        st.rerun()

# ---------------- Users
elif page == "Users":
    st.header("Users & Roles")
    with st.form("usr"):
        c = st.columns(3)
        u, p_, ro = c[0].text_input("Username"), c[1].text_input("Password", type="password"), \
            c[2].selectbox("Role", ["Admin", "HR", "Manager"])
        if st.form_submit_button("Save / reset password") and u and p_:
            q("INSERT INTO users(username,pw,role) VALUES(?,?,?) ON CONFLICT(username) "
              "DO UPDATE SET pw=excluded.pw, role=excluded.role", (u, pw(p_), ro), fetch=False)
            st.rerun()
    tbl(q("SELECT username, role FROM users"), False)
    others = [x for x in q("SELECT username FROM users").username if x != st.session_state.user]
    d = st.selectbox("Delete user", others)
    if st.button("Delete user") and d:
        q("DELETE FROM users WHERE username=?", (d,), fetch=False)
        st.rerun()

# ---------------- Payroll
elif page == "Payroll":
    st.header("Payroll")
    show_dups()
    f = pay_filters("pay")
    shown = False
    for gi, (a, b, cs) in enumerate(st.session_state["_grp_pay"]):
        raw = calc_payroll(a, b, f[2], f[3], f[4], f[5], cs, f[7], st.session_state["_cyc_pay"])
        if raw.empty:
            continue
        shown = True
        df = view_pay(raw)
        st.subheader(f"Period {a} to {b}  -  {', '.join(cs) if cs else 'All companies'}")
        tbl(df)
        c = st.columns(3)
        c[0].metric("Total Net", f"{raw.Net.sum():,.2f} {cur_}")
        c[1].metric("Company labour", f"{raw[raw.Labour == 'Company'].Net.sum():,.2f} {cur_}")
        c[2].metric("Outside labour", f"{raw[raw.Labour == 'Outside'].Net.sum():,.2f} {cur_}")
        download(df, "payroll", hdr_of(a, b, f[2], f[3], f[4], f[5], cs), str(gi))
        sel = st.selectbox("Payslip for", raw.Code + " - " + raw.Name, key=f"pslip{gi}")
        try:
            row = raw[raw.Code == sel.split(" - ")[0]].iloc[0]
            st.download_button("🧾 Download payslip PDF", payslip_pdf(row, a, b), f"payslip_{row.Code}_{a}_{b}.pdf",
                               "application/pdf", key=f"psl_btn{gi}")
        except ImportError:
            st.info("For payslip PDF run: pip install reportlab")
    if not shown:
        st.info("No attendance in this period.")

# ---------------- Costs
elif page == "Costs":
    st.header("Costs: ID/Iqama, permits, insurance, tickets, medical...")
    e, cm = emp_df(), q("SELECT * FROM companies")
    with st.form("cost"):
        c = st.columns(5)
        x = c[0].selectbox("Employee (optional)", ["-"] + (e.code + " - " + e["name"]).tolist())
        cat = c[1].selectbox("Category", ["ID / Iqama (Juazat)", "Work permit", "Insurance", "Transfer", "Muqeem / Monduf fee",
                                          "Exit re-entry", "Passport", "Medical", "Vacation ticket", "GOSI", "Other"])
        co_ = c[2].selectbox("Client company", ["-"] + cm.name.tolist())
        am, dy = c[3].number_input("Amount", 0.0), c[4].date_input("Date", today())
        nt = st.text_input("Note")
        if st.form_submit_button("Add"):
            eid = None if x == "-" else int(e[e.code == x.split(" - ")[0]].id.iloc[0])
            cid = None if co_ == "-" else int(cm[cm.name == co_].id.iloc[0])
            q("INSERT INTO costs(day,category,emp_id,company_id,amount,note) VALUES(?,?,?,?,?,?)",
              (str(dy), cat, eid, cid, am, nt), fetch=False); st.rerun()
    f = filters("cost")
    df = q("""SELECT x.id, x.day, x.category, e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, c.name AS company, d.name AS section, s.name AS sponsor,
        e.labour_type, e.pay_type, x.amount, x.note FROM costs x LEFT JOIN employees e ON e.id=x.emp_id
        LEFT JOIN companies c ON c.id=x.company_id LEFT JOIN departments d ON d.id=e.dept_id
        LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE x.day BETWEEN ? AND ?""", (f[0], f[1]))
    df = apply_f(df, *f[2:])
    tbl(df)
    tbl(df.groupby("category").amount.sum().reset_index())
    download(df, "costs", hdr_of(*f[:7]))
    rid = st.number_input("Delete cost ID", 0, step=1)
    if st.button("Delete cost") and rid:
        q("DELETE FROM costs WHERE id=?", (int(rid),), fetch=False); st.rerun()

# ---------------- Invoices
elif page == "Invoices":
    st.header("Client invoices & company-wise profit")
    f = pay_filters("inv")
    vat, shown = float(S("vat_pct")), False
    for gi, (a, b, cs) in enumerate(st.session_state["_grp_inv"]):
        p = calc_payroll(a, b, f[2], f[3], f[4], f[5], cs, f[7], st.session_state["_cyc_inv"], False)
        if p.empty:
            continue
        shown = True
        st.subheader(f"Period {a} to {b}  -  {', '.join(cs) if cs else 'All companies'}")
        g = p.groupby("Company").agg(Labour=("Code", "nunique"), Hours=("Total Hrs", "sum"), Invoice=("Invoice", "sum"),
                                     Payroll=("Net", "sum")).reset_index()
        cost = q("""SELECT COALESCE(c.name,'-') AS \"Company\", SUM(x.amount) AS \"Costs\" FROM costs x
            LEFT JOIN companies c ON c.id=x.company_id WHERE x.day BETWEEN ? AND ? GROUP BY 1""", (a, b))
        g = g.merge(cost, how="left", on="Company").fillna({"Costs": 0})
        g["VAT"] = g.Invoice * vat / 100
        g["Invoice + VAT"] = g.Invoice + g.VAT
        g["Profit"] = g.Invoice - g.Payroll - g.Costs
        g = g.round(2)
        tbl(g)
        c = st.columns(3)
        c[0].metric("Invoice (ex VAT)", f"{g.Invoice.sum():,.2f} {cur_}")
        c[1].metric("Payroll + costs", f"{g.Payroll.sum() + g.Costs.sum():,.2f} {cur_}")
        c[2].metric("Profit / Loss", f"{g.Profit.sum():,.2f} {cur_}")
        download(g, "company_profit", hdr_of(a, b, f[2], f[3], f[4], f[5], cs), str(gi))
        who = st.selectbox("Invoice detail for company", g.Company, key=f"inv_w{gi}")
        d = p[p.Company == who][["Name", "Iqama ID", "Passport No", "Section", "Total Hrs", "Invoice"]].copy()
        d["Rate/hr"] = (d.Invoice / d["Total Hrs"].where(d["Total Hrs"] > 0)).round(2)
        tbl(d)
        download(d, "invoice_" + who.replace(" ", "_"), hdr_of(a, b, f[2], f[3], f[4], f[5], cs), str(gi))
    if not shown:
        st.info("No attendance in this period.")

# ---------------- Import
# ---------------- Reports
elif page == "Reports":
    st.header("Reports ")
    kinds = ["Attendance detail", "Attendance summary", "Attendance sheet (P/A/L)", "Work history (where worked)"]
    if role != "Manager":
        kinds += ["Payroll sheet", "Company-wise", "Section-wise", "Kofil-wise", "Company x Kofil matrix",
                  "Hours (hourly basis)", "Transfer history", "ID / Iqama expiry", "EOSB provision"]
    kind = st.selectbox("Report", kinds)
    f = pay_filters("rep")
    cyc_ = st.session_state["_cyc_rep"]

    def report_df(kind, f):
        d1, d2 = f[0], f[1]

        def split(p, g):
            out = []
            for k, x in p.groupby(g):
                c_, o_ = x[x.Labour == "Company"], x[x.Labour == "Outside"]
                out.append({g: k, "Com. Persons": c_.Code.nunique(), "Com. Cash": c_.Cash.sum(), "Com. Bank": c_.Bank.sum(),
                            "Com. Subtotal": c_.Net.sum(), "Out Persons": o_.Code.nunique(), "Out Cash": o_.Cash.sum(),
                            "Out Bank": o_.Bank.sum(), "Out Subtotal": o_.Net.sum(), "Total": x.Net.sum()})
            return pd.DataFrame(out)

        J = """LEFT JOIN companies c ON c.id=a.company_id LEFT JOIN companies c0 ON c0.id=e.company_id
            LEFT JOIN departments d ON d.id=a.dept_id LEFT JOIN departments d0 ON d0.id=e.dept_id
            LEFT JOIN sponsors s ON s.id=COALESCE(a.sponsor_id,e.sponsor_id) WHERE a.day BETWEEN ? AND ?"""
        if kind == "Attendance detail":
            df = q("""SELECT a.day, e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no,
                COALESCE(c.name,c0.name) AS company, COALESCE(d.name,d0.name) AS section, s.name AS sponsor, e.labour_type,
                e.pay_type, a.status, COALESCE(a.hours,0) AS normal_hrs, COALESCE(a.ot_hours,0) AS ot_hrs,
                COALESCE(a.hours,0)+COALESCE(a.ot_hours,0) AS total_hrs FROM attendance a JOIN employees e ON e.id=a.emp_id
                """ + J + " ORDER BY a.day", (d1, d2))
            df = apply_f(df, *f[2:])
            df["status"] = df.status.replace({"Off": "No Work"})
            df = sign(df)
        elif kind == "Attendance sheet (P/A/L)":
            df = q("""SELECT e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no,
                COALESCE(c.name,c0.name,'-') AS company, COALESCE(d.name,d0.name,'-') AS section, s.name AS sponsor,
                e.labour_type, e.pay_type, e.rate AS rate, e.ot_rate AS ot_rate, e.join_date AS join_date, a.day, a.status, a.hours,
                COALESCE(a.ot_hours,0) AS ot FROM attendance a JOIN employees e ON e.id=a.emp_id """ + J, (d1, d2))
            df = apply_f(df, *f[2:])
            if len(df):
                wk = pd.to_datetime(df.day).dt.weekday == int(S("weekend"))
                pre, hh = df.status == "Present", df.hours.fillna(0)
                df["nh"] = hh.where(pre & ~wk, 0)
                df["oh"] = df.ot.where(pre & ~wk, 0) + (hh + df.ot).where(pre & wk, 0)
                df["c"], df["d"] = df.status.map(CODE).fillna("?"), df.day.str[5:]
                rt = {x.code: ot_rate_of(x.rate, x.pay_type, x.ot_rate, d2, x.join_date) for x in df.drop_duplicates("code").itertuples()}
                ix = ["code", "name", "iqama_id", "passport_no", "pay_type", "company", "section"]
                grid = df.pivot_table(index=ix, columns="d", values="c", aggfunc="first").fillna("")
                tot = df.groupby(ix).agg(P=("c", lambda x: (x == "P").sum()), A=("c", lambda x: (x == "A").sum()),
                                         L=("c", lambda x: (x == "L").sum()), No_Work=("c", lambda x: (x == "O").sum()), Normal_Hrs=("nh", "sum"), OT_Hrs=("oh", "sum"))
                tot["Total_Hrs"] = tot.Normal_Hrs + tot.OT_Hrs
                tot["OT_Rate"] = [rt[i[0]] for i in tot.index]
                tot["OT_Amount"] = (tot.OT_Hrs * tot.OT_Rate).round(2)
                if role == "Manager":
                    tot = tot.drop(columns=["OT_Rate", "OT_Amount"])
                df = sign(grid.join(tot).reset_index())
        elif kind == "Work history (where worked)":
            df = q("""SELECT e.code, e.name, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no,
                COALESCE(c.name,c0.name,'-') AS company, COALESCE(d.name,d0.name,'-') AS section, COALESCE(s.name,'-') AS sponsor,
                e.labour_type, e.pay_type, MIN(a.day) AS from_day, MAX(a.day) AS to_day, SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS days_present,
                SUM(CASE WHEN a.status='Leave' THEN 1 ELSE 0 END) AS days_leave, SUM(CASE WHEN a.status='Absent' THEN 1 ELSE 0 END) AS days_absent, SUM(CASE WHEN a.status='Off' THEN 1 ELSE 0 END) AS days_no_work,
                SUM(COALESCE(a.hours,0)) AS normal_hrs, SUM(COALESCE(a.ot_hours,0)) AS ot_hrs
                FROM attendance a JOIN employees e ON e.id=a.emp_id """ + J + " GROUP BY e.id, 5, 6, 7 ORDER BY e.code, from_day", (d1, d2))
            df = apply_f(df, *f[2:])
            df["normal_hrs"], df["ot_hrs"] = df.normal_hrs.astype(float).round(2), df.ot_hrs.astype(float).round(2)
            df["total_hrs"] = df.normal_hrs + df.ot_hrs
        elif kind == "Transfer history":
            df = trf_df(d1, d2, f[2:]).drop(columns=["id"])
        elif kind == "ID / Iqama expiry":
            e = apply_f(emp_df(), *f[2:])
            x = e.id_expiry.fillna("")
            df = e[(x >= d1) & (x <= d2) & (x != "")][["code", "name", "id_no", "passport_no", "company", "section", "sponsor",
                                                        "id_expiry"]].rename(columns={"id_no": "iqama_id"}).sort_values("id_expiry")
            df = sign(df)
        elif kind == "EOSB provision":
            out = []
            for _, r in apply_f(emp_df(), *f[2:]).iterrows():
                y, w, a_ = eosb(r, date.fromisoformat(d2))
                out.append({"Code": r.code, "Name": r["name"], "Iqama ID": r.id_no or "", "Passport No": r.passport_no or "",
                            "Company": r.company, "Section": r.section, "Sponsor": r.sponsor, "Join date": r.join_date,
                            "Years": y, "Monthly wage": w, "EOSB due": a_})
            df = sign(pd.DataFrame(out))
        else:
            p = calc_payroll(*f, cyc=cyc_)
            if kind == "Attendance summary":
                df = sign(p[["Code", "Name", "Iqama ID", "Passport No", "Company", "Section", "Sponsor", "Labour", "Pay", "Days",
                             "Leave", "Absent", "No Work", "Normal Hrs", "OT Hrs", "Wknd Hrs", "Hol Hrs", "Total Hrs"]])
            elif kind == "Payroll sheet":
                df = view_pay(p)
            elif kind == "Hours (hourly basis)":
                df = sign(p[p.Pay == "Hourly"][["Code", "Name", "Iqama ID", "Passport No", "Company", "Section", "Sponsor",
                                                "Hr Rate", "OT Rate", "Normal Hrs", "OT Hrs", "Wknd Hrs", "Hol Hrs", "Total Hrs", "Net"]])
            elif kind == "Company x Kofil matrix":
                df = p.pivot_table(index="Company", columns="Sponsor", values="Net", aggfunc="sum", fill_value=0).reset_index() if len(p) else p
            else:
                df = split(p, {"Company-wise": "Company", "Section-wise": "Section", "Kofil-wise": "Sponsor"}[kind])
        return df

    shown = False
    for gi, (a, b, cs) in enumerate(st.session_state["_grp_rep"]):
        fi = (a, b, f[2], f[3], f[4], f[5], cs, f[7])
        df = report_df(kind, fi)
        if df.empty:
            continue
        shown = True
        st.subheader(f"{kind}  |  Period {a} to {b}  -  {', '.join(cs) if cs else 'All companies'}")
        tbl(df)
        download(df, kind.replace(" ", "_").replace("(", "").replace(")", "").replace("/", ""), hdr_of(*fi[:7]), str(gi))
    if not shown:
        st.info("No data in this period.")

# ---------------- Settings
elif page == "Settings":
    st.header("Settings")
    st.info("**Pay rules in this software**  \n"
            "• **Special allowance** is a FIXED monthly amount: no reduction for absence, no penalty, no deduction.  \n"
            "• **Food and Other allowance** follow the working days (days - Fridays - special holidays).  \n"
            "• **Absence:** each absent day cuts basic / total days of the month (30 or 31) from the basic AND the same amount again as a penalty (basic only; no division by working days).  \n"
            "• **Bonus** for a full month = basic / total days of the month.  \n"
            "• **No work (O):** that day's basic is not paid, but no penalty and no food / allowance deduction.  \n"
            "• **Extra-hour pay** (set per company in Setup): a day over N hours pays 1 hour of basic = basic / (N x days of the month).  \n"
            "• **Basic increase:** the monthly basic grows by the amount below after every completed period of service from the joining date.")
    with st.form("set"):
        co = st.text_input("Company name", S("company"))
        cu = st.text_input("Currency", S("currency"))
        tzs = sorted(available_timezones())
        tz = st.selectbox("Time zone", tzs, tzs.index(S("timezone")))
        sh = st.number_input("Standard hours/day", 1.0, 24.0, float(S("std_hours")))
        wd = st.number_input("Working days/month (only for EOSB of hourly staff; monthly salary days are automatic)", 1.0, 31.0, float(S("work_days")))
        ot = st.number_input("Overtime multiplier", 1.0, 5.0, float(S("ot_mult")))
        df_ = st.selectbox("Date format", ["%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"])
        gp = st.number_input("GOSI employee deduction % (0 = off)", 0.0, 100.0, float(S("gosi_pct")))
        gn = st.text_input("GOSI applies to nationality", S("gosi_nat"))
        vp = st.number_input("VAT % on client invoices", 0.0, 100.0, float(S("vat_pct")))
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        wk = st.selectbox("Weekend OT day (hours worked this day are paid at OT rate)", days, int(S("weekend")))
        dn = st.number_input("Default normal hours (auto-filled in Attendance)", 0.0, 24.0, float(S("def_normal")))
        do_ = st.number_input("Default OT hours (auto-filled in Attendance)", 0.0, 16.0, float(S("def_ot")))
        iy = st.number_input("Basic increase: after every how many years of service", 0, 20, int(float(S("inc_years"))))
        ia = st.number_input("Basic increase: amount added to the monthly basic (0 = off)", 0.0, 100000.0, float(S("inc_amount")))
        ir = st.selectbox("Repeat the increase after every such period? (No = only once)", ["Yes", "No"], 0 if S("inc_repeat") == "Yes" else 1)
        bk = st.selectbox("Show the Bulk Attendance menu (enter many days at once)", ["Yes", "No"], 0 if S("bulk_on") == "Yes" else 1)
        c = st.columns(2)
        mon = c[0].selectbox("Dashboard scrolling text (ON / OFF)", ["Yes", "No"], 0 if S("marquee_on") == "Yes" else 1)
        mtx = c[1].text_input("Dashboard scrolling text", S("marquee_text"))
        if st.form_submit_button("Save"):
            for k, v in dict(company=co, currency=cu, timezone=tz, std_hours=sh, work_days=wd,
                             ot_mult=ot, date_fmt=df_, gosi_pct=gp, gosi_nat=gn, vat_pct=vp, weekend=days.index(wk), def_normal=dn, def_ot=do_, inc_years=iy, inc_amount=ia, inc_repeat=ir, bulk_on=bk, marquee_on=mon, marquee_text=mtx).items():
                q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)), fetch=False)
            st.success("Saved"); st.rerun()
    st.divider()
    st.subheader("Logo & print look")
    st.caption("The logo and these colours are used automatically on the header of EVERY printed page / PDF "
               "(reports, payroll, invoices, payslips). Change them here once - everything follows.")
    lc = st.columns([2, 1, 1])
    up = lc[0].file_uploader("Company logo (PNG / JPG)", type=["png", "jpg", "jpeg"], key="logo_up")
    lpos = lc[1].selectbox("Logo position on the page header", ["Left", "Center", "Right"],
                           ["Left", "Center", "Right"].index(S("logo_pos")) if S("logo_pos") in ("Left", "Center", "Right") else 0)
    lhh = lc[2].number_input("Logo height (pt)", 15, 120, int(float(S("logo_h") or 40)), 5)
    tc = st.columns(3)
    lt1 = tc[0].text_input("Logo text 1 (pink badge) - leave empty = not shown", S("logo_t1"))
    lt2 = tc[1].text_input("Logo text 2 (main line) - leave empty = not shown", S("logo_t2"))
    lt3 = tc[2].text_input("Logo text 3 (small line) - leave empty = not shown", S("logo_t3"))
    cc = st.columns(5)
    hbg = cc[0].color_picker("Header row colour", S("pdf_head_bg"))
    hfg = cc[1].color_picker("Header text colour", S("pdf_head_fg"))
    tbg = cc[2].color_picker("TOTAL row colour", S("pdf_tot_bg"))
    tfg = cc[3].color_picker("TOTAL text colour", S("pdf_tot_fg"))
    prb = cc[4].text_input("Prepared by (name, bottom left)", S("prepared_by"))
    bc = st.columns([1, 1, 4])
    if bc[0].button("💾 Save print look", key="logo_save"):
        new_logo = S("logo_b64")
        if up is not None:
            import base64
            raw_ = up.getvalue()
            try:
                from PIL import Image
                im_ = Image.open(io.BytesIO(raw_))
                im_.thumbnail((700, 400))
                buf_ = io.BytesIO()
                im_.save(buf_, format="PNG")
                raw_ = buf_.getvalue()
            except Exception:
                pass
            new_logo = base64.b64encode(raw_).decode() if len(raw_) < 600000 else ""
            if not new_logo:
                st.error("The logo file is too big - use a smaller picture.")
        for k, v in dict(logo_b64=new_logo, logo_t1=lt1, logo_t2=lt2, logo_t3=lt3, logo_pos=lpos, logo_h=lhh, prepared_by=prb, pdf_head_bg=hbg, pdf_head_fg=hfg,
                         pdf_tot_bg=tbg, pdf_tot_fg=tfg).items():
            q("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)), fetch=False)
        st.success("Saved - all new prints use it."); st.rerun()
    if bc[1].button("🗑 Remove logo", key="logo_del"):
        q("INSERT INTO settings(k,v) VALUES('logo_b64','') ON CONFLICT(k) DO UPDATE SET v=''", fetch=False)
        st.rerun()
    if S("logo_b64"):
        import base64
        st.image(base64.b64decode(S("logo_b64")), width=int(float(S("logo_h") or 40)) * 3, caption="Current logo")
    if role == "Admin" and not _restricted:
        st.divider()
        st.subheader("User access (which menu each user can open)")
        st.caption("Choose a user and tick the menus he may see in the navigation bar. A user with NO menus ticked uses the "
                   "default of his role. The main user 'admin' always sees everything. Any other user (even with role Admin) can be limited here.")
        if st.session_state.get("ua_flash"):
            st.success(st.session_state.pop("ua_flash"))
        with st.expander("➕ Add a new user (any number of users)"):
            with st.form("ua_new", clear_on_submit=True):
                c = st.columns(3)
                nu, np_, nr = c[0].text_input("Username"), c[1].text_input("Password", type="password"), \
                    c[2].selectbox("Role", ["Manager", "HR", "Admin"])
                if st.form_submit_button("Create user") and nu.strip() and np_:
                    q("INSERT INTO users(username,pw,role) VALUES(?,?,?) ON CONFLICT(username) "
                      "DO UPDATE SET pw=excluded.pw, role=excluded.role", (nu.strip(), pw(np_), nr), fetch=False)
                    st.session_state["ua_flash"] = f"User '{nu.strip()}' saved. Now choose him below and give his menu access."
                    st.rerun()
        us_ = q("SELECT username, role, perms FROM users ORDER BY username")
        us_ = us_[(us_.username != "admin") & (us_.username != st.session_state.user)]
        if us_.empty:
            st.info("No other users yet - add one with 'Add a new user' above.")
        else:
            ua = st.selectbox("User", us_.username.tolist(), key="ua_user")
            cur_p = parse_perms(us_[us_.username == ua].perms.iloc[0])
            ro_ = us_[us_.username == ua].role.iloc[0]
            grid_ = pd.DataFrame({"Menu": ALL,
                                  "Show": [m in cur_p for m in ALL],
                                  "Edit": [(("E" in cur_p[m]) if cur_p.get(m) is not None else ro_ in ("Admin", "HR")) if m in cur_p else False for m in ALL],
                                  "Delete": [(("D" in cur_p[m]) if cur_p.get(m) is not None else ro_ == "Admin") if m in cur_p else False for m in ALL]})
            ed_ = st.data_editor(grid_, hide_index=True, use_container_width=True, disabled=["Menu"], key=f"ua_g_{ua}",
                                 column_config={"Show": st.column_config.CheckboxColumn(help="Menu appears in the navigation bar"),
                                                "Edit": st.column_config.CheckboxColumn(help="Can add / change data on this menu"),
                                                "Delete": st.column_config.CheckboxColumn(help="Can delete data on this menu")})
            ch = ["%s:V%s%s" % (r_.Menu, "E" if r_.Edit else "", "D" if r_.Delete else "")
                  for r_ in ed_.itertuples(index=False) if r_.Show or r_.Edit or r_.Delete]
            oth_ = [x for x in us_.username.tolist() if x != ua]
            cp_ = st.selectbox("Copy access from another user (saves time for many users)", ["—"] + oth_, key=f"ua_cp_{ua}")
            if cp_ != "—" and st.button(f"📋 Copy {cp_}'s access to {ua}", key="ua_copy"):
                q("UPDATE users SET perms=? WHERE username=?",
                  (us_[us_.username == cp_].perms.iloc[0], ua), fetch=False)
                st.session_state["ua_flash"] = f"Copied {cp_}'s access to {ua}."
                st.session_state.pop(f"ua_g_{ua}", None)
                st.rerun()
            c = st.columns([1, 1, 4])
            if c[0].button("💾 Save access", key="ua_save"):
                q("UPDATE users SET perms=? WHERE username=?", ("|".join(ch), ua), fetch=False)
                st.session_state["ua_flash"] = (f"Saved: {ua} can open {len(ch)} menus." if ch
                                                else f"Saved: {ua} uses the default menus of his role.")
                st.rerun()
            if c[1].button("↺ Role default", key="ua_reset"):
                q("UPDATE users SET perms=NULL WHERE username=?", (ua,), fetch=False)
                st.rerun()
            fmt_ = lambda v: ", ".join(f"{k_}{' [' + ('Edit ' if 'E' in (f_ or '') else '') + ('Delete' if 'D' in (f_ or '') else '') + ']' if f_ and len(f_) > 1 else (' [view]' if f_ else '')}".replace(" ]", "]")
                                       for k_, f_ in parse_perms(v).items()) or "(role default)"
            show = us_.assign(Menus=us_.perms.map(fmt_))
            tbl(show[["username", "role", "Menus"]].rename(columns={"username": "User", "role": "Role"}), False)
    st.divider()
    st.subheader("Special holidays (Eid / special days)")
    st.caption("From the date you give, for the number of days you give. These days are left out of the month's working days "
               "(like Fridays) for the chosen Company / Kofil / Section (All = everyone). Staff who work get all their hours "
               "at the holiday rate per hour; rate 0 = their OT rate.")
    cm_, ds_, sp_ = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    c = st.columns(4)
    hf = c[0].date_input("From date", today(), key="hol_f")
    hn = c[1].number_input("Number of days", 1, 30, 1, key="hol_n")
    hco = c[2].selectbox("Company", ["All"] + cm_.name.tolist(), key="hol_c")
    hsp = c[3].selectbox("Sponsor / Kofil", ["All"] + sp_.name.tolist(), key="hol_k")
    c = st.columns(4)
    hse = c[0].selectbox("Section", ["All"] + ds_.name.tolist(), key="hol_s")
    hrt = c[1].number_input("Holiday rate per hour (0 = OT rate)", 0.0, key="hol_r")
    hnt = c[2].text_input("Note (e.g. Eid al-Fitr)", key="hol_t")
    if c[3].button("➕ Add special holiday", key="hol_add"):
        idf = lambda t, n: None if n == "All" else int(t[t.name == n].id.iloc[0])
        q("INSERT INTO holidays(from_day,to_day,company_id,dept_id,sponsor_id,rate,note) VALUES(?,?,?,?,?,?,?)",
          (str(hf), str(hf + timedelta(days=int(hn) - 1)), idf(cm_, hco), idf(ds_, hse), idf(sp_, hsp), float(hrt), hnt),
          fetch=False)
        st.session_state["flash"] = "Special holiday added"
        st.rerun()


# =====================================================================================
# EDIT / DELETE  (paste this whole block at the VERY END of hrm_app.py, no indentation)
# =====================================================================================
CAN_EDIT = ("Admin", "HR")      # roles that can edit   (change here if you want)
CAN_DELETE = ("Admin",)         # roles that can delete (change here if you want)


def manage(table, sql, params=(), edit=(), fks=None, selects=None, hide=(), used_in=(), cascade=(), key="m",
           after_upd=None, before_del=None, guard=None, flt=None, cols=None, post=None, check_upd=None):
    """Inline Edit + Delete grid for any table. `sql` must return `id` plus the columns to show."""
    can_e, can_d = _CAN_E, _CAN_D
    if not (can_e or can_d):
        return
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    fks, selects = fks or {}, selects or {}
    df = q(sql, params)
    if post is not None and not df.empty:
        df = post(df)
    dcols = date_cols(df)
    for c in dcols:
        df[c] = df[c].map(lambda v: dmy(v) if str(v) not in EMPTY else v)

    def isorow(x):   # hooks (leave sync etc.) work with ISO dates
        x = x.copy()
        for c in dcols:
            if c in x.index and str(x[c]) not in EMPTY:
                x[c] = to_iso(x[c]) or x[c]
        return x
    fsig = ""
    if flt:   # Company / Section / Kofil / Labour / Pay type boxes with 'All' inside, same as the report pages
        cos, secs, spns = (q(f"SELECT name FROM {t}").name.tolist() for t in ("companies", "departments", "sponsors"))
        c = cols or st.columns(5)
        with c[0]:
            co = eff(msel("Company", cos, flt + "_co"), cos)
        with c[1]:
            sec = eff(msel("Section", secs, flt + "_sec"), secs)
        with c[2]:
            spn = eff(msel("Sponsor / Kofil", spns, flt + "_spn"), spns)
        with c[3]:
            lt = eff(msel("Labour", ["Company", "Outside"], flt + "_lab"), ["Company", "Outside"])
        with c[4]:
            pt = eff(msel("Pay type", ["Monthly", "Hourly"], flt + "_pay"), ["Monthly", "Hourly"])
        df = apply_f(df, sec, lt, pt, spn, co).reset_index(drop=True)
        fsig = str((co, sec, spn, lt, pt))
    sq_ = search_box("🔎 Search", key + "q")
    if sq_ and not df.empty:
        df = df[df.astype(str).apply(lambda col: col.str.contains(sq_, case=False, regex=False)).any(axis=1)].reset_index(drop=True)
    if df.empty:
        st.info("No records.")
        return
    lk = {c: q(f"SELECT id,name FROM {t}") for c, (_, t) in fks.items()}
    view = df.copy()
    for c in fks:
        view[c] = view[c].fillna("")
    view.insert(0, "S/L", range(1, len(view) + 1))
    all_del = False
    if can_d:
        all_del = st.checkbox("☑ Select all rows for Delete (only the rows shown below)", key=f"{key}da{st.session_state.get(key + 'v', 0)}")
        view.insert(1, "Delete", all_del)
    cfg = {"id": None, **{h: None for h in hide}}
    for c, t in lk.items():
        cfg[c] = st.column_config.SelectboxColumn(options=[""] + t.name.tolist())
    for c, o in selects.items():
        cfg[c] = st.column_config.SelectboxColumn(options=o)
    editable = (list(edit) + list(fks)) if can_e else []
    if can_d:
        editable.append("Delete")
    ver = st.session_state.get(key + "v", 0)
    ed = st.data_editor(view, hide_index=True, use_container_width=True, column_config=cfg,
                        disabled=[c for c in view.columns if c not in editable], key=f"{key}{ver}{sq_}{fsig}{all_del}")
    _n = [c for c in ed.columns if c not in ("S/L", "id", "emp_id", "Delete", "active") and pd.api.types.is_numeric_dtype(ed[c])
          and not pd.api.types.is_bool_dtype(ed[c]) and "rate" not in c.lower()]
    if _n:
        tbl(pd.DataFrame([{"TOTAL": f"TOTAL ({len(ed)} rows)", **{c: round(float(ed[c].sum()), 2) for c in _n}}]), False)

    def done(msg):
        st.session_state[key + "v"] = ver + 1
        st.session_state["flash"] = msg
        st.rerun()

    if can_e and st.button("💾 Save changes", key=key + "s"):
        if check_upd:                       # validate ALL edited rows first, save nothing if one is wrong
            errs_ = [m_ for i_, r_ in ed.iterrows() for m_ in [check_upd(r_, view.loc[i_])] if m_]
            if errs_:
                for m_ in errs_:
                    st.error("🚫 " + m_)
                return
        n = 0
        for i, r in ed.iterrows():
            o, sets = view.loc[i], {}
            for c in list(edit) + list(fks):
                a, b = r[c], o[c]
                if (pd.isna(a) and pd.isna(b)) or a == b:
                    continue
                if c in fks:
                    t = lk[c]
                    m = t[t.name == a].id
                    sets[fks[c][0]] = int(m.iloc[0]) if len(m) else None
                else:
                    val = None if pd.isna(a) else (a.item() if hasattr(a, "item") else a)
                    if c in dcols and val not in (None, ""):
                        iso = to_iso(val)
                        if iso is None:
                            st.error(f"Row {int(r['id'])}: '{val}' is not a date - write it as DD/MM/YYYY")
                            return
                        val = iso
                    sets[c] = val
            if sets:
                try:
                    q(f"UPDATE {table} SET " + ",".join(f'"{k}"=?' for k in sets) + " WHERE id=?",
                      (*sets.values(), int(r["id"])), fetch=False)
                    if after_upd:
                        after_upd(isorow(o), isorow(r))
                    n += 1
                except Exception as ex:
                    st.error(f"Row {int(r['id'])}: {ex}")
                    return
        done(f"{n} row(s) updated")

    if can_d:
        sel = ed[ed["Delete"] == True]  # noqa: E712
        if len(sel):
            ok = st.checkbox(f"Yes, permanently delete {len(sel)} selected row(s)"
                             + (" together with their attendance, leave, adjustments and costs" if cascade else ""),
                             key=key + "ck")
            if st.button("🗑 Delete ticked rows", key=key + "d"):
                if not ok:
                    st.warning("Tick the confirm box first.")
                else:
                    errs, n = [], 0
                    for _, r in sel.iterrows():
                        i = int(r["id"])
                        msg = guard(r) if guard else None
                        busy = [t for t, c in used_in if q(f"SELECT COUNT(*) AS n FROM {t} WHERE {c}=?", (i,)).n[0]]
                        if msg or busy:
                            errs.append(msg or f"id {i} is still used in '{busy[0]}' - reassign it first")
                            continue
                        if before_del:
                            before_del(isorow(r))
                        for t, c in cascade:
                            q(f"DELETE FROM {t} WHERE {c}=?", (i,), fetch=False)
                        q(f"DELETE FROM {table} WHERE id=?", (i,), fetch=False)
                        n += 1
                    if n:
                        done(f"{n} row(s) deleted" + (" | skipped: " + " | ".join(errs) if errs else ""))
                    else:
                        st.error(" | ".join(errs))


def dr(key, cols=None):
    c = cols or st.columns(2)
    return str(dbox(c[0], "From", today().replace(day=1), key + "1")), str(dbox(c[1], "To", today(), key + "2"))


def lv_clear(r):  # remove the attendance rows an approved leave created
    if r["status"] == "Approved":
        q("DELETE FROM attendance WHERE emp_id=? AND status IN ('Leave','Absent') AND day BETWEEN ? AND ?",
          (int(r["emp_id"]), r["start"], r["end"]), fetch=False)


def lv_sync(o, r):  # after editing a leave: recalc days and rebuild its attendance rows
    s0, e0 = pd.to_datetime(r["start"]), pd.to_datetime(r["end"])
    days = int((e0 - s0).days + 1)
    q("UPDATE leaves SET days=? WHERE id=?", (days, int(r["id"])), fetch=False)
    if r["status"] == "Approved":
        lv_clear(o)
        for k in range(days):
            q("INSERT INTO attendance(emp_id,day,status,hours) VALUES(?,?,?,0) ON CONFLICT(emp_id,day) "
              "DO UPDATE SET status=excluded.status",
              (int(r["emp_id"]), str(s0.date() + timedelta(k)), "Absent" if r["ltype"] == "Unpaid" else "Leave"),
              fetch=False)


def att_post(df):   # extra display columns for the attendance records grid
    df["total_hrs"] = df.hours.fillna(0) + df.ot_hours.fillna(0)
    df["ot_rate"] = [ot_rate_of(r["_rate"], r.pay_type, r["_otr"] or 0, r.day, r["_join"]) for _, r in df.iterrows()]
    return df.drop(columns=["_rate", "_otr", "_join"])


if (_CAN_E or _CAN_D) and page in ("Commission", "Settings", "Employees", "Transfer", "Setup", "Attendance", "Leave", "Adjustments", "Costs", "Users"):
    st.divider()
    st.subheader("✏️ Edit / 🗑 Delete")
    st.caption("Choose Company / Section / Kofil (or All), change cells, then press Save. To delete: tick 'Delete', "
               "confirm, press Delete. Dates are YYYY-MM-DD.")
    EJ = (" LEFT JOIN companies c ON c.id=e.company_id LEFT JOIN departments d ON d.id=e.dept_id"
          " LEFT JOIN sponsors s ON s.id=e.sponsor_id ")
    EC = "c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type, e.pay_type"

    if page == "Employees":
        manage("employees", """SELECT e.id, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor,
            e.labour_type, e.pay_type, e.pay_mode, e.rate, e.food_allow, e.special_allow, e.other_allow, e.ot_rate, e.bill_rate, e.nationality,
            e.id_no, e.passport_no, e.phone, e.join_date, e.id_expiry, e.active FROM employees e""" + EJ + "ORDER BY e.code",
               edit=["code", "name", "labour_type", "pay_type", "pay_mode", "rate", "food_allow", "special_allow", "other_allow", "ot_rate", "bill_rate",
                     "nationality", "id_no", "passport_no", "phone", "join_date", "id_expiry", "active"],
               fks={"company": ("company_id", "companies"), "section": ("dept_id", "departments"),
                    "sponsor": ("sponsor_id", "sponsors")},
               selects={"labour_type": ["Company", "Outside"], "pay_type": ["Monthly", "Hourly"],
                        "pay_mode": ["Bank", "Cash"], "active": [1, 0]},
               cascade=[("attendance", "emp_id"), ("leaves", "emp_id"), ("adjustments", "emp_id"), ("costs", "emp_id"), ("transfers", "emp_id")],
               key="emp", flt="xemp",
               check_upd=lambda r, o: next(iter(emp_conflicts(
                   r["code"] if r["code"] != o["code"] else "", r["id_no"] if r["id_no"] != o["id_no"] else "",
                   r["passport_no"] if r["passport_no"] != o["passport_no"] else "", skip_id=int(r["id"]))), None))

    elif page == "Setup":
        t1, t2, t3 = st.tabs(["Companies", "Sections", "Sponsors / Kofil"])
        with t1:
            manage("companies", "SELECT id, name, vat, cycle_day, exh_mode, exh_hours FROM companies ORDER BY name", edit=["name", "vat", "cycle_day", "exh_mode", "exh_hours"],
                   selects={"exh_mode": ["Off", "Instead of OT", "Plus OT"]},
                   used_in=[("employees", "company_id"), ("attendance", "company_id"), ("costs", "company_id"), ("transfers", "from_company"), ("transfers", "to_company")], key="mco")
        with t2:
            manage("departments", "SELECT id, name FROM departments ORDER BY name", edit=["name"],
                   used_in=[("employees", "dept_id"), ("attendance", "dept_id"), ("transfers", "from_dept"), ("transfers", "to_dept")], key="mse")
        with t3:
            manage("sponsors", "SELECT id, name, phone, approved_by FROM sponsors ORDER BY name", edit=["name", "phone", "approved_by"],
                   used_in=[("employees", "sponsor_id"), ("attendance", "sponsor_id"), ("transfers", "from_sponsor"), ("transfers", "to_sponsor")], key="msp")

    elif page == "Attendance":
        cc = st.columns(7)
        a1, a2 = dr("mat", cc[:2])
        manage("attendance", """SELECT a.id, a.day, e.code, e.name AS employee, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no,
            e.pay_type, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type, a.status, a.hours, a.ot_hours,
            e.rate AS _rate, e.ot_rate AS _otr, e.join_date AS _join FROM attendance a
            JOIN employees e ON e.id=a.emp_id LEFT JOIN companies c ON c.id=COALESCE(a.company_id,e.company_id)
            LEFT JOIN departments d ON d.id=COALESCE(a.dept_id,e.dept_id) LEFT JOIN sponsors s ON s.id=COALESCE(a.sponsor_id,e.sponsor_id)
            WHERE a.day BETWEEN ? AND ? ORDER BY a.day DESC, e.code""", (a1, a2),
               edit=["status", "hours", "ot_hours"], selects={"status": ["Present", "Absent", "Leave", "Off"]},
               key="att", flt="xatt", cols=cc[2:], post=att_post)

    elif page == "Leave":
        cc = st.columns(7)
        a1, a2 = dr("mlv", cc[:2])
        manage("leaves", "SELECT l.id, l.emp_id, e.code, e.name AS employee, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, " + EC + ", l.ltype, l.start, l.\"end\", l.days, "
               "l.status FROM leaves l JOIN employees e ON e.id=l.emp_id" + EJ +
               "WHERE l.start<=? AND l.\"end\">=? ORDER BY l.start DESC", (a2, a1),
               edit=["ltype", "start", "end"], hide=("emp_id",),
               selects={"ltype": ["Annual", "Sick", "Emergency", "Unpaid", "Other"]},
               after_upd=lv_sync, before_del=lv_clear, key="lv", flt="xlv", cols=cc[2:])

    elif page == "Adjustments":
        cc = st.columns(7)
        a1, a2 = dr("mad", cc[:2])
        manage("adjustments", "SELECT a.id, a.day, e.code, e.name AS employee, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, " + EC + ", a.kind, a.amount, a.note "
               "FROM adjustments a JOIN employees e ON e.id=a.emp_id" + EJ +
               "WHERE a.day BETWEEN ? AND ? ORDER BY a.day DESC", (a1, a2),
               edit=["day", "kind", "amount", "note"],
               selects={"kind": ["Advance", "Deduction", "Bonus", "Allowance", "Supervisor/Operator", "Foundation Day",
                                 "Skill/Villa", "Extra", "Eid Bonus"]}, key="adj", flt="xadj", cols=cc[2:])

    elif page == "Costs":
        cc = st.columns(7)
        a1, a2 = dr("mco", cc[:2])
        manage("costs", """SELECT x.id, x.day, x.category, e.code, COALESCE(e.id_no,'') AS iqama_id, COALESCE(e.passport_no,'') AS passport_no, c.name AS company, d.name AS section, s.name AS sponsor,
            e.labour_type, e.pay_type, x.amount, x.note FROM costs x LEFT JOIN employees e ON e.id=x.emp_id
            LEFT JOIN companies c ON c.id=x.company_id LEFT JOIN departments d ON d.id=e.dept_id
            LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE x.day BETWEEN ? AND ? ORDER BY x.day DESC""", (a1, a2),
               edit=["day", "category", "amount", "note"], fks={"company": ("company_id", "companies")},
               selects={"category": ["ID / Iqama (Juazat)", "Work permit", "Insurance", "Transfer", "Muqeem / Monduf fee",
                                     "Exit re-entry", "Passport", "Medical", "Vacation ticket", "GOSI", "Other"]},
               key="cst", flt="xcost", cols=cc[2:])

    elif page == "Commission":
        manage("commissions", """SELECT k.id, k.person, k.phone, c.name AS company, d.name AS section, s.name AS sponsor, k.rate, k.note, k.active
            FROM commissions k LEFT JOIN companies c ON c.id=k.company_id LEFT JOIN departments d ON d.id=k.dept_id
            LEFT JOIN sponsors s ON s.id=k.sponsor_id ORDER BY k.person""", edit=["person", "phone", "rate", "note", "active"],
               fks={"company": ("company_id", "companies"), "section": ("dept_id", "departments"),
                    "sponsor": ("sponsor_id", "sponsors")}, selects={"active": [1, 0]}, key="com")
        st.caption("Active 1 = counted in the report, 0 = paused. Empty Company / Section / Kofil = no limit.")

    elif page == "Settings":
        manage("holidays", """SELECT h.id, h.from_day, h.to_day, c.name AS company, d.name AS section, s.name AS sponsor,
            h.rate, h.note FROM holidays h LEFT JOIN companies c ON c.id=h.company_id
            LEFT JOIN departments d ON d.id=h.dept_id LEFT JOIN sponsors s ON s.id=h.sponsor_id ORDER BY h.from_day DESC""",
               edit=["from_day", "to_day", "rate", "note"],
               fks={"company": ("company_id", "companies"), "section": ("dept_id", "departments"),
                    "sponsor": ("sponsor_id", "sponsors")}, key="hol")
        st.caption("Empty Company / Section / Kofil = applies to everyone. Dates are YYYY-MM-DD.")

    elif page == "Transfer":
        cc = st.columns(7)
        a1, a2 = dr("mtr", cc[:2])
        manage("transfers", TRF_SQL, (a1, a2), edit=["day", "note"], key="trn", flt="xtrf", cols=cc[2:])
        st.caption("Deleting a history line does not move the employee back - make a new transfer for that.")

    elif page == "Users":
        manage("users", "SELECT id, username, role FROM users ORDER BY username", edit=["username", "role"],
               selects={"role": ["Admin", "HR", "Manager"]},
               guard=lambda r: "You cannot delete the user you are logged in as"
               if r["username"] == st.session_state.user else None, key="usr")
