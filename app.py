from flask import Flask, render_template, request
from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

@app.route("/health")
def health():
    return "OK", 200


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        xml_file = request.files.get("xml_file")
        xml_text = request.form.get("xml_text", "").strip()

        if not xml_file and not xml_text:
            return render_template("index.html", error="請上傳 XML 檔案或貼上 XML 內容。")

        if xml_file:
            xml_bytes = xml_file.read()
            xml_text = xml_bytes.decode("utf-8", errors="ignore")

        try:
            row = parse_hrv_xml_to_row(xml_text)
        except Exception as e:
            return render_template("index.html", error=f"XML 解析失敗：{e}")

        # --- 映射到 HTML 的變數 ---
        ctx = {
            "name": row.get("Name"),
            "sex": row.get("Sex"),
            "age": row.get("Age"),
            "test_date": row.get("TestDate"),

            "LF": row.get("LF"),
            "HF": row.get("HF"),
            "TP": row.get("TP"),
            "ln_ratio": row.get("ln_LF_HF"),
            "ln_TP": row.get("ln_TP"),
            "TP_Q": row.get("TP_Q"),

            "constitution": row.get("Constitution"),
            "advice": get_constitution_advice(row.get("Constitution", "")),
            "quadrant_img": generate_quadrant_plot_base64(row),
        }

        return render_template("report.html", **ctx)

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
