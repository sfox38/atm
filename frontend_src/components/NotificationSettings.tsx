import React from "react";
import type { GlobalSettings } from "../types";

interface Props {
  settings: GlobalSettings;
  onToggle: (key: keyof GlobalSettings, value: boolean) => void;
  saving: boolean;
}

export function NotificationSettings({ settings, onToggle, saving }: Props) {
  return (
    <div>
      <div className="toggle-row">
        <div className="toggle-label">
          <span>Notify on rate limit breach</span>
          <small>
            Sends a HA persistent notification when any token hits its rate limit. Throttled to one notification per token per minute.
          </small>
        </div>
        <label className={`toggle-checkbox-label${saving ? " disabled" : ""}`}>
          <input
            type="checkbox"
            checked={settings.notify_on_rate_limit}
            disabled={saving}
            onChange={(e) => onToggle("notify_on_rate_limit", e.target.checked)}
            className="toggle-checkbox"
          />
        </label>
      </div>
    </div>
  );
}
