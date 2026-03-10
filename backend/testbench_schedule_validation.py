from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import httpx


_BASE_URL_ENV = "SUSANOH_TESTBENCH_STAGING_BASE_URL"
_USERNAME_ENV = "SUSANOH_TESTBENCH_STAGING_USERNAME"
_PASSWORD_ENV = "SUSANOH_TESTBENCH_STAGING_PASSWORD"
_API_KEY_ENV = "SUSANOH_TESTBENCH_STAGING_API_KEY"


@dataclass(frozen=True)
class RegressionLiveValidation:
    configured: bool
    missing: tuple[str, ...]
    default_username: str | None
    notes: tuple[str, ...]


def probe_staging_api_key_requirement(base_url: str, timeout_seconds: float = 5.0) -> bool | None:
    normalized = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.post(f"{normalized}/api/v1/auth/token")
    except httpx.HTTPError:
        return None

    detail = None
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict):
        raw_detail = payload.get("detail")
        if isinstance(raw_detail, str):
            detail = raw_detail

    if response.status_code == 401 and detail and "X-API-KEY" in detail:
        return True

    return False


def validate_regression_live_configuration(env: Mapping[str, str]) -> RegressionLiveValidation:
    missing: list[str] = []
    notes: list[str] = []

    base_url = env.get(_BASE_URL_ENV, "").strip()
    password = env.get(_PASSWORD_ENV, "").strip()
    username = env.get(_USERNAME_ENV, "").strip()
    api_key = env.get(_API_KEY_ENV, "").strip()

    if not base_url:
        missing.append(_BASE_URL_ENV)
    if not password:
        missing.append(_PASSWORD_ENV)

    if base_url and not api_key:
        api_key_required = probe_staging_api_key_requirement(base_url)
        if api_key_required is True:
            missing.append(_API_KEY_ENV)
            notes.append(
                "Staging preflight indicates X-API-KEY is required for /api/v1/auth/token."
            )
        elif api_key_required is None:
            notes.append(
                "Could not determine whether staging requires X-API-KEY; continuing without a preflight skip."
            )

    return RegressionLiveValidation(
        configured=not missing,
        missing=tuple(missing),
        default_username="admin" if not username else None,
        notes=tuple(notes),
    )


def write_github_metadata(
    validation: RegressionLiveValidation,
    *,
    github_output: str | None = None,
    github_step_summary: str | None = None,
    github_env: str | None = None,
) -> None:
    if github_output:
        _append_lines(Path(github_output), [f"configured={'true' if validation.configured else 'false'}"])

    if github_env and validation.default_username:
        _append_lines(Path(github_env), [f"{_USERNAME_ENV}={validation.default_username}"])

    if github_step_summary and (not validation.configured or validation.notes):
        lines: list[str] = []
        if validation.configured:
            lines.append("Regression-Live preflight passed.")
        else:
            lines.extend(
                [
                    "Regression-Live skipped.",
                    "",
                    f"Missing required secrets: {' '.join(validation.missing)}",
                ]
            )

        if validation.notes:
            if lines:
                lines.append("")
            lines.extend(f"- {note}" for note in validation.notes)

        _append_lines(Path(github_step_summary), lines)


def _append_lines(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Regression-Live workflow staging configuration.")
    parser.add_argument("--github-output")
    parser.add_argument("--github-step-summary")
    parser.add_argument("--github-env")
    args = parser.parse_args(argv)

    validation = validate_regression_live_configuration(env=os.environ)
    write_github_metadata(
        validation,
        github_output=args.github_output,
        github_step_summary=args.github_step_summary,
        github_env=args.github_env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
