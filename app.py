# app.py
from flask import Flask, render_template, request

from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
    get_constitution_explain_html,
    build_overall_summary,
)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        # 初始畫面，只給體質說明那一段 HTML
        explain_html = get_constitution_explain_html()
        return render_template(
            "index.html",
            row=None,
            quad_img_b64=None,
            error=None,
            constitution=None,
            advice_text=None,
            summary_text=None,
            explain_html=explain_html,
        )

    # POST：處理上傳 / 貼上的 XML
    xml_file = request.files.get("xml_file")
    xml_text = request.form.get("xml_text", "").strip()

    if not xml_file and not xml_text:
        explain_html = get_constitution_explain_html()
        return render_template(
            "index.html",
            row=None,
            quad_img_b64=None,
            error="請上傳 XML 檔案或貼上 XML 內容。",
            constitution=None,
            advice_text=None,
            summary_text=None,
            explain_html=explain_html,
        )

    # 1) 優先使用上傳檔案，其次使用貼上的文字
    if xml_file:
        try:
            xml_bytes = xml_file.read()
            xml_text = xml_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            explain_html = get_constitution_explain_html()
            return render_template(
                "index.html",
                row=None,
                quad_img_b64=None,
                error=f"XML 檔案讀取失敗：{e}",
                constitution=None,
                advice_text=None,
                summary_text=None,
                explain_html=explain_html,
            )

    # 2) 呼叫核心解析
    try:
        row = parse_hrv_xml_to_row(xml_text)
    except Exception as e:
        explain_html = get_constitution_explain_html()
        return render_template(
            "index.html",
            row=None,
            quad_img_b64=None,
            error=f"XML 解析失敗：{e}",
            constitution=None,
            advice_text=None,
            summary_text=None,
            explain_html=explain_html,
        )

    # 3) 產生四象限圖
    try:
        quad_img_b64 = generate_quadrant_plot_base64(row)
    except Exception as e:
        quad_img_b64 = None
        error_msg = f"四象限圖產生失敗：{e}"
    else:
        error_msg = None

    # 4) 體質與建議 / summary
    constitution = row.get("Constitution", "資料不足")
    advice_text = get_constitution_advice(constitution)
    summary_text = build_overall_summary(row)
    explain_html = get_constitution_explain_html()

    return render_template(
        "index.html",
        row=row,
        quad_img_b64=quad_img_b64,
        error=error_msg,
        constitution=constitution,
        advice_text=advice_text,
        summary_text=summary_text,
        explain_html=explain_html,
    )


if __name__ == "__main__":
    # 開發模式
    app.run(host="0.0.0.0", port=5001, debug=True)

