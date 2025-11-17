# hrv_core.py
# HRV XML 解析 + 陰陽虛實體質判讀 + 四象限圖（含 Kuo(1999) TP 基準 Healthy Zone）
# + BMI / ANS Age / ANS Age Diff 判讀整合版

import math
import os
import io
import base64
import re
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as patches


# ========= 字型設定 =========
_BASE_DIR = os.path.dirname(__file__)

FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Bold.ttf"),
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Black.ttf"),
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/PingFang TC.ttc",
    "C:/Windows/Fonts/msjh.ttc",
]

_FONT_PROP = None

def _get_font_prop():
    global _FONT_PROP
    if _FONT_PROP is not None:
        return _FONT_PROP

    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                _FONT_PROP = fm.FontProperties(fname=path)
                print(f"[Font] Using font: {path}")
                return _FONT_PROP
            except Exception:
                continue

    _FONT_PROP = fm.FontProperties()
    print("[Font] Using default font")
    return _FONT_PROP


# ========= 年齡 × 性別 TP 基準（Kuo 1999） =========
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


# ========= 安全工具 =========
def safe_float(x, default=0.0):
    try: return float(x)
    except: return default

def safe_int(x, default=0):
    try: return int(float(x))
    except: return default

def safe_ln(x):
    x = safe_float(x)
    if x <= 0: return float("nan")
    return math.log(x)


# ========= TP 參考基準 =========
def get_tp_mu_sigma(age, sex):
    sex = sex.strip() if sex else "男"
    if sex not in TP_BASE:
        sex = "男"

    for max_age, mu, sigma in TP_BASE[sex]:
        if age <= max_age:
            return mu, sigma

    return 6.0, 0.5


# ========= Healthy Zone =========
def get_healthy_zone(age, sex):
    mu_lnTP, sigma_lnTP = get_tp_mu_sigma(age, sex)
    return (
        mu_lnTP - sigma_lnTP,
        mu_lnTP + sigma_lnTP,
        -0.5,
        0.5
    )


# ========= XML 清理 =========
def _extract_patient_xml(xml_text):
    s = (xml_text or "").strip()
    if not s: return ""

    if "<Patient" in s:
        m = re.search(r"<Patient\b[^>]*\/>", s)
        if m: return m.group(0)
        return s

    if s.startswith("Patient "):
        return "<" + s

    return s


# ========= 主解析：parse_hrv_xml_to_row =========
def parse_hrv_xml_to_row(xml_text):
    xml_clean = _extract_patient_xml(xml_text)
    if not xml_clean:
        raise ValueError("XML 內容為空")

    root = ET.fromstring(xml_clean)
    if root.tag != "Patient":
        root = root.find(".//Patient")
        if root is None:
            raise ValueError("找不到 <Patient>")

    attr = root.attrib

    # 基本欄位
    name = attr.get("Name", "")
    sex = attr.get("Sex", "")
    pid = attr.get("ID", "")
    height = safe_float(attr.get("Height", 0))
    weight = safe_float(attr.get("Weight", 0))
    age = safe_int(attr.get("Age", 0))
    test_date = attr.get("TestDate", "")

    hr = safe_int(attr.get("HR", 0))
    sd = safe_float(attr.get("SD", 0))
    rv = safe_float(attr.get("RV", 0))
    er = safe_int(attr.get("ER", 0))
    n = safe_int(attr.get("N", 0))

    tp = safe_float(attr.get("TP", 0))
    vl = safe_float(attr.get("VL", 0))
    lf = safe_float(attr.get("LF", 0))
    hf = safe_float(attr.get("HF", 0))
    nn = safe_int(attr.get("NN", 0))
    balance = safe_float(attr.get("Balance", 0))

    # ln values
    ln_tp = safe_ln(tp)
    ln_ratio = safe_ln(lf / hf) if hf > 0 else float("nan")

    # TP_Q (能量效率)
    mu, sigma = get_tp_mu_sigma(age, sex)
    tp_q = (ln_tp - mu) / sigma if sigma > 0 and not math.isnan(ln_tp) else float("nan")

    # ====== (1) BMI ======
    height_m = height / 100 if height > 5 else height
    bmi = weight / (height_m ** 2) if height_m > 0 else float("nan")

    if bmi < 18.5:
        bmi_status = "體重過輕"
    elif bmi < 23:
        bmi_status = "正常"
    elif bmi < 25:
        bmi_status = "過重（前期）"
    elif bmi < 30:
        bmi_status = "肥胖（中度）"
    else:
        bmi_status = "肥胖（重度）"

    # ====== (2) ANS Age ======
    ans_age_min = safe_int(attr.get("ANSAgeMIN", 0))
    ans_age_max = safe_int(attr.get("ANSAgeMAX", 0))

    if ans_age_min > 0 and ans_age_max > 0:
        ans_age = round((ans_age_min + ans_age_max) / 2)
    else:
        ans_age = float("nan")

    # ====== (3) ANS Age Diff ======
    ans_age_diff = ans_age - age if not math.isnan(ans_age) else float("nan")

    # ====== 陰陽虛實分類 ======
    constitution = classify_constitution(ln_tp, ln_ratio)

    # ====== 組裝 row ======
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

        # 新增欄位
        "BMI": round(bmi, 2),
        "BMI_Status": bmi_status,
        "ANS_Age": ans_age,
        "ANS_Age_Diff": ans_age_diff,
    }

    return row


# ========= 陰陽虛實分類 =========
def classify_constitution(ln_tp, ln_ratio):
    if math.isnan(ln_tp) or math.isnan(ln_ratio):
        return "資料不足"

    if ln_tp >= 6 and ln_ratio >= 0:
        return "陽實型"
    if ln_tp < 6 and ln_ratio >= 0:
        return "陽虛型"
    if ln_tp >= 6 and ln_ratio < 0:
        return "陰實型"
    return "陰虛型"


# ========= 體質建議 =========
def get_constitution_advice(c):
    c = c.strip()

    if c == "陽實型":
        return ("【陽實型】交感神經偏強、能量偏高。\n"
                "建議：放鬆練習、減少刺激、留意血壓。")

    if c == "陽虛型":
        return ("【陽虛型】交感主導但能量不足。\n"
                "建議：規律運動、溫補飲食、改善睡眠。")

    if c == "陰實型":
        return ("【陰實型】副交感偏強但能量高。\n"
                "建議：控制飲食、增加活動、改善代謝。")

    if c == "陰虛型":
        return ("【陰虛型】副交感與能量皆偏低。\n"
                "建議：充足睡眠、均衡飲食、溫和運動。")

    return "資料不足，無法判讀。"


# ========= 四象限圖 =========
def generate_quadrant_plot_base64(row):
    x = safe_float(row.get("ln_TP"))
    y = safe_float(row.get("ln_LF_HF"))

    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", ""))

    font_prop = _get_font_prop()

    plt.figure(figsize=(5,5), dpi=120)
    ax = plt.gca()

    # 分界線
    ax.axvline(6.0, color="gray", linestyle="--")
    ax.axhline(0.0, color="gray", linestyle="--")

    # Healthy zone
    hx_min, hx_max, hy_min, hy_max = get_healthy_zone(age, sex)
    rect = patches.Rectangle(
        (hx_min, hy_min), hx_max-hx_min, hy_max-hy_min,
        edgecolor="green", facecolor="green", alpha=0.2
    )
    ax.add_patch(rect)

    # 標籤
    ax.text(x, y, " 測量點", color="red", fontproperties=font_prop)
    ax.scatter(x, y, s=80, color="red")

    labels = [
        (6.8, 0.8, "陽實型"),
        (5.2, 0.8, "陽虛型"),
        (5.2, -0.8, "陰虛型"),
        (6.8, -0.8, "陰實型"),
    ]
    for lx, ly, t in labels:
        ax.text(lx, ly, t, fontproperties=font_prop, alpha=0.7)

    ax.set_xlabel("ln(TP)（虛 → 實）", fontproperties=font_prop)
    ax.set_ylabel("ln(LF/HF)（陰 → 陽）", fontproperties=font_prop)

    ax.grid(alpha=0.3)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("utf-8")
