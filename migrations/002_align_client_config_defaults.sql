ALTER TABLE client_configs
    ALTER COLUMN owner_notification_channel SET DEFAULT 'telegram',
    ALTER COLUMN process_leads_frequency SET DEFAULT 'every_2h_weekdays',
    ALTER COLUMN automation_status SET DEFAULT 'demo_manual',
    ALTER COLUMN required_disclaimer SET DEFAULT 'Reply STOP to opt out.',
    ALTER COLUMN voice SET DEFAULT 'friendly, concise, professional';

ALTER TABLE client_configs
    DROP CONSTRAINT IF EXISTS client_configs_automation_status_check;

ALTER TABLE client_configs
    ADD CONSTRAINT client_configs_automation_status_check
    CHECK (automation_status IN ('demo_manual', 'draft', 'active', 'paused'));
