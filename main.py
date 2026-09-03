"""
AutoDeploy UI — точка входа.
"""
from core.logging_setup import configure_logging
from ui.app import Application

configure_logging()

if __name__ == "__main__":
    app = Application()
    app.run()
