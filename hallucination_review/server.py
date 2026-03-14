import csv
import os
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "hallucination_review", "review.csv")
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

app = Flask(__name__)


def read_csv():
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "label" not in row:
                row["label"] = ""
            rows.append(row)
    return rows


def write_field(session, line, field, value):
    """Generic: update any single field for a matching row."""
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        if field not in fieldnames:
            fieldnames.append(field)
        for row in reader:
            if row["session"] == session and row["line"] == str(line):
                row[field] = value
            if field not in row:
                row[field] = ""
            rows.append(row)

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.route("/api/data")
def get_data():
    return jsonify(read_csv())


@app.route("/api/label", methods=["POST"])
def set_label():
    data = request.json
    try:
        write_field(data["session"], data["line"], "label", data["label"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/correction", methods=["POST"])
def set_correction():
    data = request.json
    try:
        write_field(data["session"], data["line"], "correction", data["correction"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/audio/<path:filepath>")
def serve_audio(filepath):
    review_dir = os.path.dirname(os.path.abspath(__file__))
    full = os.path.join(review_dir, filepath)
    if not os.path.isfile(full):
        return "Not found", 404
    return send_file(full)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"開啟瀏覽器：http://localhost:{port}")
    try:
        from waitress import serve
        print("使用 waitress server")
        serve(app, host="127.0.0.1", port=port, threads=8)
    except ImportError:
        print("waitress 未安裝，使用 Flask dev server（pip install waitress 可改善效能）")
        app.run(port=port, debug=False, threaded=True)
