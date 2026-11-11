# -*- coding: utf-8 -*-
"""PChome vs MOMO 商品價格比較（Streamlit）

執行：streamlit run compare_app.py
"""
import re
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from curl_cffi import requests as cffi_requests

# ---------------- 常數 ----------------
PCHOME_API = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
PCHOME_HEADERS = {"User-Agent": "Mozilla/5.0"}

MOMO_API = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
MOMO_HOME = "https://www.momoshop.com.tw/"
MOMO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}

COLORS = {"PChome": "#1f77b4", "MOMO": "#e8590c"}
COLUMNS = ["平台", "頁數", "品名", "價格"]


# ---------------- 共用工具 ----------------
def to_int(value):
    """把 '1,299'、599、599.0 之類的值轉成整數；無法轉換回傳 None。"""
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return int(float(m.group())) if m else None


# ---------------- PChome ----------------
@st.cache_data(show_spinner=False, ttl=600)
def scrape_pchome(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    rows = []
    for page in range(1, pages + 1):
        resp = requests.get(
            PCHOME_API,
            params={"q": keyword, "page": page, "sort": "sale/dc"},
            headers=PCHOME_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        prods = resp.json().get("prods", [])
        if not prods:
            break
        for p in prods:
            rows.append({"平台": "PChome", "頁數": page,
                         "品名": p.get("name", ""), "價格": to_int(p.get("price"))})
        if page < pages:
            time.sleep(delay)
    return _finalize(rows)


# ---------------- MOMO ----------------
def momo_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def scrape_momo(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    session = cffi_requests.Session(impersonate="chrome")
    session.get(MOMO_HOME, headers=MOMO_HEADERS)  # 先取得 cookie
    rows = []
    for page in range(1, pages + 1):
        resp = session.post(MOMO_API, headers=MOMO_HEADERS, json=momo_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁 HTTP {resp.status_code}：{resp.text[:200]}")
        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:
            break
        for p in goods:
            rows.append({"平台": "MOMO", "頁數": page,
                         "品名": p.get("goodsName", ""), "價格": to_int(p.get("goodsPrice"))})
        if page < pages:
            time.sleep(delay)
    return _finalize(rows)


def _finalize(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.dropna(subset=["價格"]).copy()
    df["價格"] = df["價格"].astype(int)
    return df.reset_index(drop=True)


SCRAPERS = {"PChome": scrape_pchome, "MOMO": scrape_momo}


# ---------------- 分析工具 ----------------
def extract_brand(name: str) -> str:
    """取品名中第一組【】內文字當品牌；沒有就歸為「其他」（簡易規則，非精準）。"""
    m = re.search(r"【(.+?)】", name)
    return m.group(1).strip() if m else "其他"


def add_price_bins(df: pd.DataFrame, n_bins: int):
    """兩平台合併後用同一組分位數切區間，才能公平比較。回傳 (df, 區間順序)。"""
    out = df.copy()
    try:
        codes, edges = pd.qcut(out["價格"], q=n_bins, labels=False,
                               retbins=True, duplicates="drop")
    except ValueError:  # 價格全部相同等情況
        out["價格區間"] = "全部"
        return out, ["全部"]
    edges = [int(round(e)) for e in edges]
    label_of = {i: f"{edges[i]:,}–{edges[i + 1]:,}" for i in range(len(edges) - 1)}
    out["價格區間"] = codes.map(label_of)
    order = [label_of[i] for i in sorted(label_of)]
    return out, order


# ---------------- UI ----------------
st.set_page_config(page_title="PChome vs MOMO 價格比較", layout="wide")
st.title("PChome vs MOMO 商品價格比較")

with st.sidebar:
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("每個平台爬取頁數", min_value=1, max_value=10, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.5, 0.5)
    platforms = st.multiselect("比較平台", list(SCRAPERS), default=list(SCRAPERS))
    n_bins = st.slider("價格區間數（圓餅/旭日/柱狀）", 3, 8, 5)
    top_n_line = st.slider("折線圖每平台顯示筆數", 10, 300, 80, 10)
    top_n_brand = st.slider("旭日圖每平台顯示前幾大品牌", 3, 15, 6)
    run = st.button("開始爬取", type="primary")

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    if not platforms:
        st.warning("請至少選一個平台")
        st.stop()
    frames, errors = [], []
    for name in platforms:
        try:
            with st.spinner(f"爬取 {name} 中…"):
                part = SCRAPERS[name](keyword.strip(), int(pages), float(delay))
            if part.empty:
                errors.append(f"{name}：沒有取得資料（可能被擋或關鍵字無結果）")
            else:
                frames.append(part)
        except Exception as e:  # 單一平台失敗不影響另一個
            errors.append(f"{name} 爬取失敗：{e}")
    st.session_state["data"] = (pd.concat(frames, ignore_index=True)
                                if frames else pd.DataFrame(columns=COLUMNS))
    st.session_state["errors"] = errors
    st.session_state["kw"] = keyword.strip()

data = st.session_state.get("data")
if data is None:
    st.info("請在左側輸入產品名稱與頁數，按「開始爬取」。")
    st.stop()
for msg in st.session_state.get("errors", []):
    st.warning(msg)
if data.empty:
    st.error("沒有取得任何資料。")
    st.stop()

kw = st.session_state["kw"]
df, bin_order = add_price_bins(data, n_bins)
df["品牌"] = df["品名"].apply(extract_brand)
present = [p for p in COLORS if p in set(df["平台"])]

# 統計摘要
stats = (df.groupby("平台")["價格"]
         .agg(商品數="count", 平均價="mean", 中位數="median", 最高價="max", 最低價="min")
         .reindex(present))
cols = st.columns(len(present))
for col, p in zip(cols, present):
    r = stats.loc[p]
    col.subheader(p)
    col.metric("商品數", f"{int(r['商品數'])}")
    col.metric("平均價", f"{r['平均價']:,.0f}")
    col.caption(f"中位數 {r['中位數']:,.0f}｜最高 {r['最高價']:,.0f}｜最低 {r['最低價']:,.0f}")

tab_line, tab_bar, tab_pie, tab_sun, tab_data = st.tabs(
    ["折線圖", "柱狀圖", "圓餅圖", "旭日圖", "資料表"])

with tab_line:
    d = df.groupby("平台").head(top_n_line).copy()
    d["序號"] = d.groupby("平台").cumcount() + 1
    fig = px.line(d, x="序號", y="價格", color="平台", hover_name="品名", markers=True,
                  color_discrete_map=COLORS, title=f"「{kw}」售價（依各平台搜尋結果順序）")
    for p in present:
        fig.add_hline(y=stats.loc[p, "平均價"], line_dash="dash", line_color=COLORS[p],
                      annotation_text=f"{p} 平均 {stats.loc[p, '平均價']:,.0f}")
    st.plotly_chart(fig, width="stretch")

with tab_bar:
    c1, c2 = st.columns(2)
    with c1:
        m = (stats[["平均價", "中位數", "最高價", "最低價"]].reset_index()
             .melt(id_vars="平台", var_name="指標", value_name="價格"))
        fig = px.bar(m, x="指標", y="價格", color="平台", barmode="group",
                     color_discrete_map=COLORS, text_auto=",.0f", title="價格統計比較")
        st.plotly_chart(fig, width="stretch")
    with c2:
        cnt = df.groupby(["價格區間", "平台"]).size().reset_index(name="商品數")
        fig = px.bar(cnt, x="價格區間", y="商品數", color="平台", barmode="group",
                     color_discrete_map=COLORS, text_auto=True,
                     category_orders={"價格區間": bin_order}, title="各價格區間商品數")
        st.plotly_chart(fig, width="stretch")

with tab_pie:
    st.caption("兩平台使用同一組價格區間（以合併資料的分位數切分）。")
    pcols = st.columns(len(present))
    for col, p in zip(pcols, present):
        pie = df[df["平台"] == p]["價格區間"].value_counts().reset_index()
        pie.columns = ["價格區間", "商品數"]
        fig = px.pie(pie, names="價格區間", values="商品數", title=f"{p} 價格區間占比",
                     category_orders={"價格區間": bin_order})
        col.plotly_chart(fig, width="stretch")

with tab_sun:
    parts = []
    for p in present:
        sub = df[df["平台"] == p].copy()
        top = sub["品牌"].value_counts().head(top_n_brand).index
        sub.loc[~sub["品牌"].isin(top), "品牌"] = "其他"
        parts.append(sub)
    sun = (pd.concat(parts).groupby(["平台", "價格區間", "品牌"]).size()
           .reset_index(name="數量"))
    fig = px.sunburst(sun, path=["平台", "價格區間", "品牌"], values="數量",
                      color="平台", color_discrete_map=COLORS,
                      title=f"「{kw}」平台 → 價格區間 → 品牌")
    st.plotly_chart(fig, width="stretch")
    st.caption("品牌為取品名中第一組【】內文字的簡易規則，沒有【】者歸為「其他」。")

with tab_data:
    st.dataframe(df[["平台", "頁數", "品名", "價格", "價格區間", "品牌"]],
                 width="stretch")
    st.download_button(
        "下載 CSV",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{time.strftime('%Y%m%d')}_compare_{kw}.csv",
        mime="text/csv",
    )
