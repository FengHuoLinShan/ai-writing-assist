#!/usr/bin/env python3
"""Render the 1Panel OpenResty site without exposing secret values."""

from __future__ import annotations

import argparse
from pathlib import Path

from validate_env import parse_env, validate


def main() -> int:
    deploy_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=deploy_dir / ".env.production")
    parser.add_argument(
        "--template",
        type=Path,
        default=deploy_dir / "openresty/site.conf.template",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    values = parse_env(args.env)
    errors = validate(values)
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1

    rendered = args.template.read_text(encoding="utf-8")
    replacements = {
        "__DEPLOY_DOMAIN__": values["DEPLOY_DOMAIN"],
        "__TLS_CERTIFICATE_PATH__": values["TLS_CERTIFICATE_PATH"],
        "__TLS_CERTIFICATE_KEY_PATH__": values["TLS_CERTIFICATE_KEY_PATH"],
        "__API_LOOPBACK_PORT__": values["API_LOOPBACK_PORT"],
        "__FRONTEND_LOOPBACK_PORT__": values["FRONTEND_LOOPBACK_PORT"],
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    if "__" in rendered:
        print("Rendered OpenResty config still contains unresolved placeholders.")
        return 1

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
