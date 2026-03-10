import httpx

from backend.testbench_schedule_validation import (
    probe_staging_api_key_requirement,
    validate_regression_live_configuration,
    write_github_metadata,
)


def test_probe_staging_api_key_requirement_detects_api_key_gate(monkeypatch):
    class _Response:
        status_code = 401

        @staticmethod
        def json():
            return {"detail": "Missing X-API-KEY header"}

    class _Client:
        def __init__(self, *, timeout, follow_redirects):
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url: str):
            assert url == "https://staging.example.com/api/v1/auth/token"
            return _Response()

    monkeypatch.setattr("backend.testbench_schedule_validation.httpx.Client", _Client)

    assert probe_staging_api_key_requirement("https://staging.example.com/") is True


def test_validate_regression_live_configuration_requires_api_key_when_probe_demands_it(monkeypatch):
    monkeypatch.setattr(
        "backend.testbench_schedule_validation.probe_staging_api_key_requirement",
        lambda _base_url, timeout_seconds=5.0: True,
    )

    validation = validate_regression_live_configuration(
        {
            "SUSANOH_TESTBENCH_STAGING_BASE_URL": "https://staging.example.com",
            "SUSANOH_TESTBENCH_STAGING_PASSWORD": "secret",
        }
    )

    assert validation.configured is False
    assert validation.missing == ("SUSANOH_TESTBENCH_STAGING_API_KEY",)
    assert validation.default_username == "admin"


def test_validate_regression_live_configuration_keeps_api_key_optional_when_probe_allows_it(monkeypatch):
    monkeypatch.setattr(
        "backend.testbench_schedule_validation.probe_staging_api_key_requirement",
        lambda _base_url, timeout_seconds=5.0: False,
    )

    validation = validate_regression_live_configuration(
        {
            "SUSANOH_TESTBENCH_STAGING_BASE_URL": "https://staging.example.com",
            "SUSANOH_TESTBENCH_STAGING_PASSWORD": "secret",
            "SUSANOH_TESTBENCH_STAGING_USERNAME": "ops-admin",
        }
    )

    assert validation.configured is True
    assert validation.missing == ()
    assert validation.default_username is None


def test_validate_regression_live_configuration_keeps_running_when_probe_is_indeterminate(monkeypatch):
    monkeypatch.setattr(
        "backend.testbench_schedule_validation.probe_staging_api_key_requirement",
        lambda _base_url, timeout_seconds=5.0: None,
    )

    validation = validate_regression_live_configuration(
        {
            "SUSANOH_TESTBENCH_STAGING_BASE_URL": "https://staging.example.com",
            "SUSANOH_TESTBENCH_STAGING_PASSWORD": "secret",
        }
    )

    assert validation.configured is True
    assert validation.notes == (
        "Could not determine whether staging requires X-API-KEY; continuing without a preflight skip.",
    )


def test_write_github_metadata_records_outputs(tmp_path):
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "summary.md"
    env_path = tmp_path / "github-env.txt"

    validation = validate_regression_live_configuration(
        {
            "SUSANOH_TESTBENCH_STAGING_BASE_URL": "",
            "SUSANOH_TESTBENCH_STAGING_PASSWORD": "",
        }
    )

    write_github_metadata(
        validation,
        github_output=str(output_path),
        github_step_summary=str(summary_path),
        github_env=str(env_path),
    )

    assert output_path.read_text(encoding="utf-8") == "configured=false\n"
    assert "Regression-Live skipped." in summary_path.read_text(encoding="utf-8")
    assert env_path.read_text(encoding="utf-8") == "SUSANOH_TESTBENCH_STAGING_USERNAME=admin\n"


def test_probe_staging_api_key_requirement_returns_none_on_network_error(monkeypatch):
    class _Client:
        def __init__(self, *, timeout, follow_redirects):
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url: str):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr("backend.testbench_schedule_validation.httpx.Client", _Client)

    assert probe_staging_api_key_requirement("https://staging.example.com/") is None
