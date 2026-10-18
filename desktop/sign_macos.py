"""Ephemeral runner keychain and Developer ID notarization; never print credentials."""

import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path


def run(*args, capture=False):
    result = subprocess.run(
        args, check=False, text=True, stdout=subprocess.PIPE if capture else None
    )
    if result.returncode:
        raise SystemExit("macOS signing command failed: " + args[0])
    return result.stdout


def main():
    directory = Path(os.environ["RUNNER_TEMP"])
    keychain = str(directory / "novelcraft-signing.keychain-db")
    if sys.argv[1] == "cleanup":
        if Path(keychain).exists():
            run("security", "delete-keychain", keychain)
        return
    if sys.argv[1] == "prepare":
        required = [
            "MACOS_CERTIFICATE_P12",
            "MACOS_CERTIFICATE_PASSWORD",
            "NOVELCRAFT_CODESIGN_IDENTITY",
            "APPLE_ID",
            "APPLE_TEAM_ID",
            "APPLE_APP_PASSWORD",
        ]
        if any(not os.environ.get(name) for name in required):
            raise SystemExit(
                "Stable release requires all documented Apple signing secrets"
            )
        certificate = directory / "novelcraft-signing.p12"
        certificate.write_bytes(
            base64.b64decode(os.environ["MACOS_CERTIFICATE_P12"], validate=True)
        )
        password = secrets.token_urlsafe(32)
        try:
            run("security", "create-keychain", "-p", password, keychain)
            run("security", "set-keychain-settings", "-lut", "21600", keychain)
            run("security", "unlock-keychain", "-p", password, keychain)
            run(
                "security",
                "import",
                str(certificate),
                "-k",
                keychain,
                "-P",
                os.environ["MACOS_CERTIFICATE_PASSWORD"],
                "-T",
                "/usr/bin/codesign",
            )
            run(
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:",
                "-k",
                password,
                keychain,
            )
            existing = run("security", "list-keychains", "-d", "user", capture=True)
            import shlex

            run(
                "security",
                "list-keychains",
                "-d",
                "user",
                "-s",
                keychain,
                *shlex.split(existing),
            )
        finally:
            certificate.unlink(missing_ok=True)
    else:
        image = sys.argv[2]
        run("codesign", "--verify", "--deep", "--strict", "desktop/dist/NovelCraft.app")
        run(
            "codesign",
            "--force",
            "--timestamp",
            "--sign",
            os.environ["NOVELCRAFT_CODESIGN_IDENTITY"],
            image,
        )
        result = json.loads(
            run(
                "xcrun",
                "notarytool",
                "submit",
                image,
                "--apple-id",
                os.environ["APPLE_ID"],
                "--team-id",
                os.environ["APPLE_TEAM_ID"],
                "--password",
                os.environ["APPLE_APP_PASSWORD"],
                "--wait",
                "--timeout",
                "20m",
                "--output-format",
                "json",
                capture=True,
            )
        )
        if result.get("status") != "Accepted":
            raise SystemExit("Apple notarization did not accept this package")
        run("xcrun", "stapler", "staple", image)
        run("xcrun", "stapler", "validate", image)


if __name__ == "__main__":
    main()
