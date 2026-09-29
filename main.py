import webview

from app.api import Api
from app.db.database import init_db

if __name__ == "__main__":
    init_db()
    api = Api()
    window = webview.create_window(
        "Router Agent",
        "frontend/index.html",
        js_api=api,
        width=1000,
        height=750,
        min_size=(700, 500),
        text_select=True,
    )
    api.window = window  # needed for the native folder picker in Code mode
    webview.start()
