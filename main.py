"""ASGI entrypoint.

Run with:  uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1

The app is built by :func:`chaka.factory.create_app`. To customize, build your
own here instead — e.g. inject a custom handler/manager, or subclass
``ChakaApplicationFactory`` and call its ``create_app``.
"""

from __future__ import annotations

from chaka import factory

# Module-level ASGI app so `uvicorn main:app` works.
app = factory.create_app()


def main():
    app.run()


if __name__ == '__main__':
    main()
