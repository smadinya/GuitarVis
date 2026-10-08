"""Settings come from GUITARVIS_* variables; the defaults match compose.yaml."""

import pytest
from guitarvis_jobs.settings import Settings


def test_defaults_match_compose_and_the_spec() -> None:
    settings = Settings()

    assert settings.database_url == (
        "postgresql+psycopg://guitarvis:guitarvis@localhost:5432/guitarvis"
    )
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.s3_endpoint == "http://localhost:9000"
    assert settings.s3_public_endpoint == "http://localhost:9000"
    assert settings.s3_bucket == "guitarvis"
    assert settings.max_upload_mb == 150
    assert settings.max_active_jobs_per_ip == 2
    assert settings.job_timeout_sec == 1800
    assert settings.device is None


def test_from_env_reads_prefixed_variables() -> None:
    settings = Settings.from_env(
        {
            "GUITARVIS_REDIS_URL": "redis://elsewhere:6380/2",
            "GUITARVIS_MAX_UPLOAD_MB": "20",
            "GUITARVIS_DEVICE": "cuda",
        }
    )

    assert settings.redis_url == "redis://elsewhere:6380/2"
    assert settings.max_upload_mb == 20
    assert settings.device == "cuda"


def test_an_empty_variable_means_the_default() -> None:
    assert Settings.from_env({"GUITARVIS_MAX_UPLOAD_MB": ""}).max_upload_mb == 150


def test_unrelated_variables_are_ignored() -> None:
    assert Settings.from_env({"DATABASE_URL": "x", "GUITARVIS_NOPE": "y"}) == Settings()


def test_a_malformed_number_names_the_variable() -> None:
    with pytest.raises(ValueError, match="GUITARVIS_JOB_TIMEOUT_SEC"):
        Settings.from_env({"GUITARVIS_JOB_TIMEOUT_SEC": "half an hour"})


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        Settings.from_env({"GUITARVIS_MAX_ACTIVE_JOBS_PER_IP": "0"})


def test_from_env_defaults_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUITARVIS_S3_BUCKET", "other")

    assert Settings.from_env().s3_bucket == "other"


def test_max_upload_bytes_is_mebibytes() -> None:
    assert Settings(max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024
