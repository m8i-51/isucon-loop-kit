from flask import Flask

app = Flask(__name__)


@app.route("/api/foo")
def api_foo():
    return {"ok": True}


@app.route("/api/bar")
def api_bar():
    return {"ok": True}
