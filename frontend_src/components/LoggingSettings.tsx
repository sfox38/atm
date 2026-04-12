import React from "react";
import type { GlobalSettings } from "../types";

interface Props {
  settings: GlobalSettings;
  onToggle: (key: keyof GlobalSettings, value: boolean) => void;
  saving: boolean;
}

const TOGGLES: {
  key: keyof Pick<
    GlobalSettings,
    "disable_all_logging" | "log_allowed" | "log_denied" | "log_rate_limited" | "log_entity_names" | "log_client_ip"
  >;
  label: string;
  description: string;
  master?: boolean;
}[] = [
  {
    key: "disable_all_logging",
    label: "Disable all logging",
    description: "Master switch. When ON, all logging is suppressed. Sensor counters still increment.",
    master: true,
  },
  {
    key: "log_allowed",
    label: "Log allowed requests",
    description: "Records 'allowed' outcomes in the audit log.",
  },
  {
    key: "log_denied",
    label: "Log denied requests",
    description: "Records 'denied' and 'not_found' outcomes in the audit log.",
  },
  {
    key: "log_rate_limited",
    label: "Log rate limited requests",
    description: "Records 'rate_limited' outcomes in the audit log.",
  },
  {
    key: "log_entity_names",
    label: "Log entity names",
    description: "Includes entity IDs in log entries. When off, resource field shows [redacted].",
  },
  {
    key: "log_client_ip",
    label: "Log client IP",
    description: "Includes source IP in log entries. When off, IP field shows [redacted].",
  },
];

export function LoggingSettings({ settings, onToggle, saving }: Props) {
  const masterOff = settings.disable_all_logging;

  return (
    <div>
      {TOGGLES.map(({ key, label, description, master }) => {
        const greyed = !master && masterOff;
        return (
          <div
            key={key}
            className="toggle-row"
            style={{ opacity: greyed ? 0.5 : 1 }}
          >
            <div className="toggle-label">
              <span style={{ fontWeight: master ? 500 : undefined }}>{label}</span>
              <small>{description}</small>
            </div>
            <label style={{ display: "flex", alignItems: "center", cursor: (saving || greyed) ? "not-allowed" : "pointer" }}>
              <input
                type="checkbox"
                checked={settings[key] as boolean}
                disabled={saving || greyed}
                onChange={(e) => onToggle(key, e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--primary-color, #03a9f4)", cursor: "inherit" }}
              />
            </label>
          </div>
        );
      })}
    </div>
  );
}
