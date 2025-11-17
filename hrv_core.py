# hrv_core.py
# HRV XML 解析 + 陰陽虛實體質判讀 + 四象限圖（含 Kuo(1999) TP 基準 Healthy Zone）

import math
import os
import io
import base64
import re
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")  # ✅ 不啟用 GUI backend，適合 Flask / 伺服器環境

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as patches


# ========= 字型設定 =========
# 優先使用專案內 /static/NotoSansTC-*.ttf，跨平台避免中文變豆腐

_BASE_DIR = os.path.dirname(__file__)

FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Bold.ttf"),
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Black.ttf"),
    "/System/Library/Fonts/PingFang.ttc",     # macOS
    "/Library/Fonts/PingFang TC.ttc",
    "C:/Windows/Fonts/msjh.ttc",              # Windows 微軟正黑體
]

_FONT_PROP = None


def _get_font_prop():
    """嘗試載入中文字型，優先用專案內的 NotoSansTC。"""
    global _FONT_PROP
    if _FONT_PROP is not None:
        return _FONT_PROP

    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                _FONT_PROP = fm.FontProperties(fname=path)
                print(f"[Font] Using font: {path}")
                return _FONT_PROP
            except Exception as e:
                print(f"[Font] Failed to load {path}: {e}")
                continue

    # fallback：就算沒有中文字型，也不要讓程式掛掉
    _FONT_PROP = fm.FontProperties()
    print("[Font] No custom font found, using default font.")
    return _FONT_PROP


# ========= Kuo(1999) 年齡 × 性別 TP 基準（ln 值） =========
# 每個 tuple: (最大年齡, TP_ln_平均, TP_ln_標準差)

TP_BASE = {
    "男": [
        (29, 6.8, 0.5),
        (39, 6.5, 0.5),
        (49, 6.2, 0.6),
        (59, 5.8, 0.6),
        (69, 5.5, 0.7),
        (200, 5.2, 0.7),
    ],
    "女": [
        (29, 6.6, 0.5),
        (39, 6.4, 0.5),
        (49, 6.0, 0.5),
        (59, 5.6, 0.5),
        (69, 5.2, 0.5),
        (200, 4.9, 0.5),
    ],
}


# ========= 基本工具函式 =========

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default


def safe_ln(x):
    """ln，遇到 <=0 回傳 nan。"""
    x = safe_float(x, default=0.0)
    if x <= 0:
        return float("nan")
    return math.log(x)


# ========= 依 Kuo(1999) 回傳對應年齡 × 性別的 lnTP μ, σ =========

def get_tp_mu_sigma(age: int, sex: str):
    sex = (sex or "").strip()
    if sex not in TP_BASE:
        sex = "男"  # default

    mu_lnTP = 6.0
    sigma_lnTP = 0.5

    for max_age, mu, sigma in TP_BASE[sex]:
        if age <= max_age:
            mu_lnTP = mu
            sigma_lnTP = sigma
            break

    return mu_lnTP, sigma_lnTP


# ========= Healthy Zone 定義 =========

def get_healthy_zone(age: int, sex: str):
    """
    根據 Kuo (1999) 年齡 × 性別 TP 基準，回傳：
      (x_min, x_max, y_min, y_max)

    x 方向：ln(TP) 的正常區 = μ ± σ
    y 方向：ln(LF/HF) 先固定用 [-0.5, 0.5] 作為交感 / 副交感平衡帶。
    """
    mu_lnTP, sigma_lnTP = get_tp_mu_sigma(age, sex)

    x_min = mu_lnTP - sigma_lnTP
    x_max = mu_lnTP + sigma_lnTP

    y_min = -0.5
    y_max = 0.5

    return x_min, x_max, y_min, y_max


# ========= XML 相關 =========

def _extract_patient_xml(xml_text: str) -> str:
    """
    嘗試從輸入文字中抓出 <Patient ... /> 這一段：
    - 若已經是完整 <Patient .../>，直接回傳
    - 若是 `Patient .../>` → 自動補上 `<`
    - 若是一整段 XML，內含 <Patient .../> → 用 regex 抓出來
    """
    s = (xml_text or "").strip()
    if not s:
        return ""

    # 若一整段有 <Patient ... />
    if "<Patient" in s:
        m = re.search(r"<Patient\b[^>]*\/>", s)
        if m:
            return m.group(0)
        # 如果不是 self-closing，最後再退回原文給 ET 判斷
        return s

    # 若只是以 "Patient " 開頭沒加 `<`
    if s.startswith("Patient "):
        return "<" + s

    return s


def parse_hrv_xml_to_row(xml_text: str) -> dict:
    """
    解析單筆 HRV XML（或內含 Patient 標籤的字串），
    回傳一個 dict，包含：
      Name, Sex, Age, ID, Height, Weight, TestDate,
      HR, SD, RV, ER, N,
      TP, VL, LF, HF, NN, Balance,
      ln_LF_HF, ln_TP, TP_Q, Constitution
    """
    xml_clean = _extract_patient_xml(xml_text)
    if not xml_clean:
        raise ValueError("XML 內容為空，無法解析")

    root = ET.fromstring(xml_clean)
    # 若 root 不是 Patient，再找底下的 Patient tag
    if root.tag != "Patient":
        patient = root.find(".//Patient")
        if patient is None:
            raise ValueError("找不到 <Patient> 標籤")
        elem = patient
    else:
        elem = root

    attr = elem.attrib

    name = attr.get("Name", "")
    sex = attr.get("Sex", "").strip()
    pid = attr.get("ID", "")
    height = safe_float(attr.get("Height", 0))
    weight = safe_float(attr.get("Weight", 0))
    age = safe_int(attr.get("Age", 0))
    test_date = attr.get("TestDate", "")  # 給報告用的測量日期

    hr = safe_int(attr.get("HR", 0))
    sd = safe_float(attr.get("SD", 0.0))
    rv = safe_float(attr.get("RV", 0.0))
    er = safe_int(attr.get("ER", 0))
    n = safe_int(attr.get("N", 0))

    tp = safe_float(attr.get("TP", 0.0))
    vl = safe_float(attr.get("VL", 0.0))
    lf = safe_float(attr.get("LF", 0.0))
    hf = safe_float(attr.get("HF", 0.0))
    nn = safe_int(attr.get("NN", 0))
    balance = safe_float(attr.get("Balance", 0.0))

    # ln 值
    ln_tp = safe_ln(tp)
    ln_ratio = safe_ln(lf / hf) if hf > 0 else float("nan")

    # Kuo 基準 → TP_Q = (lnTP - μ) / σ（z-score）
    mu_lnTP, sigma_lnTP = get_tp_mu_sigma(age, sex)
    if sigma_lnTP > 0 and not math.isnan(ln_tp):
        tp_q = (ln_tp - mu_lnTP) / sigma_lnTP
    else:
        tp_q = float("nan")

    # 體質分類（陰陽 × 虛實）
    constitution = classify_constitution(ln_tp, ln_ratio)

    row = {
        "Name": name,
        "Sex": sex,
        "ID": pid,
        "Height": round(height, 2),
        "Weight": round(weight, 2),
        "Age": age,
        "TestDate": test_date,
        "HR": hr,
        "SD": round(sd, 2),
        "RV": round(rv, 2),
        "ER": er,
        "N": n,
        "TP": round(tp, 2),
        "VL": round(vl, 2),
        "LF": round(lf, 2),
        "HF": round(hf, 2),
        "NN": nn,
        "Balance": round(balance, 2),
        "ln_TP": round(ln_tp, 2) if not math.isnan(ln_tp) else float("nan"),
        "ln_LF_HF": round(ln_ratio, 2) if not math.isnan(ln_ratio) else float("nan"),
        "TP_Q": round(tp_q, 2) if not math.isnan(tp_q) else float("nan"),
        "Constitution": constitution,
    }
    return row


# ========= 體質分類（陰陽虛實） =========

def classify_constitution(ln_tp: float, ln_ratio: float) -> str:
    """
    依 HRV 四象限定義體質：
      X = ln(TP)：虛 ←→ 實
      Y = ln(LF/HF)：陰 ←→ 陽

    門檻設計：
      - 實 / 虛 分界：lnTP ≈ 6（可之後調整或改成 μ 基準）
      - 陽 / 陰 分界：ln(LF/HF) = 0
    """
    if math.isnan(ln_tp) or math.isnan(ln_ratio):
        return "資料不足"

    x_thr = 6.0
    y_thr = 0.0

    if ln_tp >= x_thr and ln_ratio >= y_thr:
        return "陽實型"
    elif ln_tp < x_thr and ln_ratio >= y_thr:
        return "陽虛型"
    elif ln_tp >= x_thr and ln_ratio < y_thr:
        return "陰實型"
    else:
        return "陰虛型"


# ========= 體質建議文字 =========

def get_constitution_advice(constitution: str) -> str:
    c = (constitution or "").strip()

    if c == "陽實型":
        return (
            "【陽實型】交感神經偏強、整體能量偏高，常見狀態：容易緊繃、火氣大、睡眠較淺、"
            "血壓偏高或情緒急躁等。建議：\n"
            "1. 加強放鬆訓練（腹式呼吸、伸展、正念練習）。\n"
            "2. 晚上避免過度刺激（咖啡因、重口味、激烈運動、3C 過度使用）。\n"
            "3. 規律作息，留意血壓與心血管風險。\n"
        )

    if c == "陽虛型":
        return (
            "【陽虛型】交感神經主導但能量不足，像是『油門踩著但引擎馬力不夠』，"
            "常見狀態：容易疲倦、手腳冰冷、精神不佳。建議：\n"
            "1. 白天適度日照與規律輕度運動，逐步養成體力。\n"
            "2. 飲食上可偏向溫和補氣（溫熱性食材，避免生冷冰品）。\n"
            "3. 睡眠品質要穩定，避免長期熬夜透支。\n"
        )

    if c == "陰實型":
        return (
            "【陰實型】副交感偏強但整體能量仍高，像是『煞車踩得較多但油箱也滿』，"
            "常見狀態：代謝偏慢、容易水腫、疲倦但又睡不飽。建議：\n"
            "1. 規律運動促進循環與代謝，避免久坐不動。\n"
            "2. 飲食控制總熱量與精緻澱粉，減少身體過度負擔。\n"
            "3. 留意體重、血脂與血糖等代謝指標。\n"
        )

    if c == "陰虛型":
        return (
            "【陰虛型】副交感與整體能量都偏低，像是『油箱偏空、休息也補不太起來』，"
            "常見狀態：容易疲倦、恢復慢、免疫力較弱。建議：\n"
            "1. 建立固定的睡眠與起床時間，先把「休息品質」顧好。\n"
            "2. 以溫和運動慢慢養體力，不要一開始就做太激烈的訓練。\n"
            "3. 飲食均衡、適度補充蛋白質與足量水分，必要時與醫師討論慢性病風險。\n"
        )

    if c == "資料不足":
        return "目前可用的 HRV 資料不足，無法可靠判讀陰陽虛實，建議重新測量一次以利評估。"

    # fallback
    return "此體質標籤目前沒有對應的建議說明，可再檢查原始資料或重新量測。"


# ========= 四象限圖：回傳 base64 PNG =========

def generate_quadrant_plot_base64(row: dict) -> str:
    """
    根據 row 內的 ln_TP / ln_LF_HF 畫四象限圖，並標示：
      - Kuo 基準 Healthy Zone（綠色矩形）
      - 個人位置（紅點）
      - 四象限標籤
    回傳 base64 PNG 字串，可直接在 HTML <img> 使用。
    """
    x = safe_float(row.get("ln_TP", float("nan")))
    y = safe_float(row.get("ln_LF_HF", float("nan")))

    x_threshold = 6.0   # 虛實分界
    y_threshold = 0.0   # 陰陽分界

    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", "")).strip()

    font_prop = _get_font_prop()

    plt.figure(figsize=(5, 5), dpi=120)
    ax = plt.gca()

    # 象限分界線
    ax.axvline(x=x_threshold, color="gray", linestyle="--", linewidth=1)
    ax.axhline(y=y_threshold, color="gray", linestyle="--", linewidth=1)

    # Healthy Zone（根據年齡 × 性別）
    hx_min, hx_max, hy_min, hy_max = get_healthy_zone(age, sex)
    rect = patches.Rectangle(
        (hx_min, hy_min),
        hx_max - hx_min,
        hy_max - hy_min,
        linewidth=1,
        edgecolor="green",
        facecolor="green",
        alpha=0.15,
    )
    ax.add_patch(rect)

    # 正常區標籤
    hz_label_x = (hx_min + hx_max) / 2
    hz_label_y = (hy_min + hy_max) / 2
    label_text = "正常參考區"
    ax.text(
        hz_label_x, hz_label_y, label_text,
        fontproperties=font_prop, color="green",
        ha="center", va="center"
    )

    # 個人紅點
    ax.scatter(x, y, s=80, color="red", zorder=5)
    ax.text(
        x, y, "  測量點",
        fontproperties=font_prop, fontsize=9,
        va="center", color="red"
    )

    # 四個象限標籤
    quad_labels = [
        (x_threshold + 0.8, y_threshold + 0.8, "陽實型"),
        (x_threshold - 0.8, y_threshold + 0.8, "陽虛型"),
        (x_threshold - 0.8, y_threshold - 0.8, "陰虛型"),
        (x_threshold + 0.8, y_threshold - 0.8, "陰實型"),
    ]
    for qx, qy, text in quad_labels:
        ax.text(
            qx, qy, text,
            fontproperties=font_prop,
            fontsize=10, alpha=0.8,
            ha="center", va="center"
        )

    # 軸標籤
    ax.set_xlabel("ln(TP)（虛  →  實）", fontproperties=font_prop)
    ax.set_ylabel("ln(LF/HF)（陰  →  陽）", fontproperties=font_prop)

    # 根據測量 + 正常區決定顯示範圍
    x_min = min(x, x_threshold, hx_min)
    x_max = max(x, x_threshold, hx_max)
    y_min = min(y, y_threshold, hy_min)
    y_max = max(y, y_threshold, hy_max)

    ax.set_xlim(x_min - 1, x_max + 1)
    ax.set_ylim(y_min - 1, y_max + 1)

    ax.grid(alpha=0.3)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)

    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    return img_b64
