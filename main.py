"""
AutoDeploy UI — точка входа.
"""
from core.logging_setup import configure_logging


def main() -> None:
    """Run the original Tkinter client (kept for migration compatibility)."""
    configure_logging()
    from ui.app import Application

    app = Application()
    app.run()

if __name__ == "__main__":
    main()
