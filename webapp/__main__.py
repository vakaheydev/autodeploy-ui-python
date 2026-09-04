"""``python -m webapp`` entry point."""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

from webapp.app import create_app
from webapp.settings import WebSettings


def main() -> None:
    settings = WebSettings.load()
    if settings.open_browser:
        threading.Timer(
            1.0,
            lambda: webbrowser.open(f"http://{settings.host}:{settings.port}"),
        ).start()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
