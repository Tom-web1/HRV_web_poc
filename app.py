# app.py
import io
from flask import Flask, render_template, request, make_response
from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
)
from xhtml2pdf import pisa
import base64

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

# 保存最新一次 HTML（用來匯出 PDF）
latest_pdf_html = None


@app.route("/health")
def health():
    return "OK", 200


@app.route("/", methods=["GET", "POST"])
def index():
    global latest_pdf_html

    if request.method == "POST":
        xml_file = request.files.get("xml_file")
        xml_text = request.form.get("xml_text", "").strip()

        if not xml_file and not xml_text:
            return render_template("index.html", error="請上傳 XML 檔案或貼上 XML 內容。")

        # 讀取上傳檔案
        if xml_file:
            xml_bytes = xml_file.read()
            xml_text = xml_bytes.decode("utf-8", errors="ignore")

        # 解析 XML
        try:
            row = parse_hrv_xml_to_row(xml_text)
        except Exception as e:
            return render_template("index.html", error=f"XML 解析失敗：{e}")

        # 建立四象限圖
        quad_img_b64 = generate_quadrant_plot_base64(row)
        advice = get_constitution_advice(row["Constitution"])

        # ===== 建立報告 HTML（準備 PDF 用）=====
        latest_pdf_html = render_template(
            "report.html",
            row=row,
            advice=advice,
            quad_img_b64=quad_img_b64,
        )

        # ===== 回傳畫面 =====
        return latest_pdf_html

    # GET
    return render_template("index.html")


# ========== PDF 匯出 ==========
@app.route("/export_pdf")
def export_pdf():
    global latest_pdf_html

    if not latest_pdf_html:
        return "請先完成一次 HRV 分析，再下載 PDF。", 400

    # ----- xhtml2pdf 產生 PDF -----
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        latest_pdf_html,
        dest=pdf_buffer,
        encoding="utf-8"
    )

    if pisa_status.err:
        return "PDF 產生失敗，請稍後再試。", 500

    pdf_buffer.seek(0)

    # ----- PDF 檔名：HRV_REPORT_<Name>.pdf -----
    try:
        name = "Unknown"
        # 嘗試從 HTML 找出 name（row.Name）
        import re
        m = re.search(r"姓名：([^<]+)", latest_pdf_html)
        if m:
            name = m.group(1).strip()

        filename = f"HRV_REPORT_{name}.pdf"
    except:
        filename = "HRV_REPORT.pdf"

    # ----- 回傳 PDF -----
    response = make_response(pdf_buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"

    return response


if __name__ == "__main__":
    app.run(debug=True)

