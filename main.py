"""
AutoDeploy UI — точка входа.
"""
import logging

from ui.app import Application

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8", mode="a"),
    ],
)
# Уменьшаем шум от urllib3 / tkinter / PIL если они появятся
logging.getLogger("urllib3").setLevel(logging.WARNING)

if __name__ == "__main__":
    app = Application()
    app.run()
