from pathlib import Path

import yaml

from groot_ops.config_loader import load_client_config
from groot_ops.ui_config_service import (
    build_client_config_dict,
    parse_spreadsheet_id,
    safe_config_path,
    slugify_client_id,
    validate_setup,
    write_client_config,
)


def test_parse_spreadsheet_id_from_url_and_raw_id():
    assert parse_spreadsheet_id("sheet123") == "sheet123"
    assert parse_spreadsheet_id("https://docs.google.com/spreadsheets/d/abcDEF123/edit#gid=0") == "abcDEF123"


def test_build_client_config_dict_uses_safe_defaults():
    data = build_client_config_dict(
        {
            "business_name": "Evergreen Realty",
            "agent_name": "Ada Agent",
            "agent_phone": "+15550100",
            "agent_email": "ada@example.com",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "owner_channel": "email",
            "owner_destination": "ada@example.com",
        }
    )

    assert data["client_id"] == "evergreen_realty_ada_agent"
    assert data["repository"]["type"] == "google_sheets"
    assert data["repository"]["spreadsheet_id"] == "sheet123"
    assert data["repository"]["credentials_env"] == "MATON_API_KEY"
    assert data["notifications"]["owner_channel"] == "email"
    assert data["schedule"]["automation_status"] == "demo_manual"


def test_write_client_config_round_trips_new_ui_sections(tmp_path: Path):
    data = build_client_config_dict(
        {
            "business_name": "Pilot Realty",
            "agent_name": "Rex",
            "agent_phone": "555",
            "agent_email": "rex@example.com",
            "spreadsheet_url": "sheet123",
            "daily_summary_time": "09:15",
            "process_leads_frequency": "daily_weekdays",
        }
    )
    path = tmp_path / "pilot.yaml"
    write_client_config(path, data)

    raw = yaml.safe_load(path.read_text())
    config = load_client_config(path)

    assert raw["notifications"]["owner_channel"] == "telegram"
    assert config.owner_notification_channel == "telegram"
    assert config.daily_summary_time == "09:15"
    assert config.process_leads_frequency == "daily_weekdays"


def test_safe_config_path_stays_under_base_dir(tmp_path: Path):
    path = safe_config_path("../../Bad Client", base_dir=tmp_path)
    assert path.parent == tmp_path.resolve()
    assert path.name == "bad_client.yaml"


def test_validate_setup_warns_when_google_env_missing(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    data = build_client_config_dict(
        {
            "business_name": "Pilot Realty",
            "agent_name": "Rex",
            "agent_phone": "555",
            "agent_email": "rex@example.com",
            "spreadsheet_url": "sheet123",
        }
    )
    path = tmp_path / "pilot.yaml"
    write_client_config(path, data)
    config = load_client_config(path)

    checks = validate_setup(config)

    assert any(check.label == "Google access" and check.status == "warn" for check in checks)


def test_build_client_config_dict_persists_confirmed_column_mapping():
    data = build_client_config_dict(
        {
            "business_name": "Pilot Realty",
            "agent_name": "Rex",
            "agent_phone": "555",
            "agent_email": "rex@example.com",
            "spreadsheet_url": "sheet123",
            "column_name": "Client Name",
            "column_phone": "WhatsApp Number",
            "column_budget": "Price Range",
            "column_desired_location": "Preferred Area",
            "column_timeline": "Move-in Timeline",
            "column_message": "Inquiry Notes",
        }
    )

    assert data["repository"]["column_mapping"] == {
        "name": "Client Name",
        "phone": "WhatsApp Number",
        "budget": "Price Range",
        "desired_location": "Preferred Area",
        "timeline": "Move-in Timeline",
        "message": "Inquiry Notes",
    }


def test_load_client_config_round_trips_column_mapping(tmp_path: Path):
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
                "  credentials_env: MATON_API_KEY",
                "  column_mapping:",
                "    name: Client Name",
                "    phone: WhatsApp Number",
            ]
        ),
        encoding="utf-8",
    )

    config = load_client_config(config_path)

    assert config.column_mapping == {"name": "Client Name", "phone": "WhatsApp Number"}
