from pathlib import Path

from groot_ops.config_loader import load_client_config


def test_load_sample_config_resolves_csv_path():
    config = load_client_config("configs/sample_realtor.yaml")

    assert config.client_id == "sample_realtor"
    assert config.business_name == "Evergreen Realty Group"
    assert config.leads_csv.endswith("data/sample_leads.csv")
    assert config.required_disclaimer == "Reply STOP to opt out."


def test_relative_repository_paths_resolve_from_config_file_directory(tmp_path: Path):
    config_dir = tmp_path / "client_configs" / "nested"
    data_dir = tmp_path / "client_configs" / "data"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    config_path = config_dir / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: nested_client",
                "business_name: Nested Realty",
                "agent_name: Agent",
                "agent_phone: '555-0100'",
                "agent_email: agent@example.invalid",
                "repository:",
                "  type: csv",
                "  leads_csv: ../data/leads.csv",
                "  activity_log_csv: ../data/activity_log.csv",
            ]
        ),
        encoding="utf-8",
    )

    config = load_client_config(config_path)

    assert config.leads_csv == str((data_dir / "leads.csv").resolve())
    assert config.activity_log_csv == str((data_dir / "activity_log.csv").resolve())


def test_load_google_sheets_config_fields(tmp_path: Path):
    config_path = tmp_path / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: pilot_client",
                "business_name: Pilot Realty",
                "agent_name: Agent",
                "agent_phone: '555-0100'",
                "agent_email: agent@example.invalid",
                "repository:",
                "  type: google_sheets",
                "  spreadsheet_id: sheet123",
                "  leads_sheet: Leads",
                "  activity_log_sheet: Activity Log",
                "  credentials_env: GROOT_GOOGLE_SERVICE_ACCOUNT_JSON",
            ]
        ),
        encoding="utf-8",
    )

    config = load_client_config(config_path)

    assert config.repository_type == "google_sheets"
    assert config.spreadsheet_id == "sheet123"
    assert config.leads_sheet == "Leads"
    assert config.activity_log_sheet == "Activity Log"
    assert config.credentials_env == "GROOT_GOOGLE_SERVICE_ACCOUNT_JSON"
