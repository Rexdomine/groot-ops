from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Groot Ops lightweight demo UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Use 127.0.0.1 for local-only demos.")
    parser.add_argument("--port", type=int, default=8080, help="Bind port.")
    args = parser.parse_args()
    print(f"Groot Ops demo UI: http://{args.host}:{args.port}")
    uvicorn.run("groot_ops.ui_app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
