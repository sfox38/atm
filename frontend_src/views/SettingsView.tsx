import React, { useEffect, useState } from "react";
import type { GlobalSettings } from "../types";
import { api } from "../api";
import { LoggingSettings } from "../components/LoggingSettings";
import { NotificationSettings } from "../components/NotificationSettings";
import { KillSwitch } from "../components/KillSwitch";
import { WipeConfirmModal } from "../components/WipeConfirmModal";
import { Loading } from "../index";
import { JS_BUILD } from "../version";

const GITHUB_URL = "https://github.com/sfox38/atm";

interface Props {
  settings: GlobalSettings | null;
  onSettingsChange: (s: GlobalSettings) => void;
}

export function SettingsView({ settings, onSettingsChange }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showWipe, setShowWipe] = useState(false);
  const [atmVersion, setAtmVersion] = useState<string | null>(null);
  const [minHaVersion, setMinHaVersion] = useState<string | null>(null);

  useEffect(() => {
    api.getInfo().then((info) => {
      setAtmVersion(info.version);
      setMinHaVersion(info.min_ha_version);
    }).catch(() => {});
  }, []);

  async function patchSetting(key: keyof GlobalSettings, value: boolean | number) {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.patchSettings({ [key]: value });
      onSettingsChange(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save setting.");
    } finally {
      setSaving(false);
    }
  }

  function handleWiped() {
    setShowWipe(false);
    window.location.reload();
  }

  if (!settings) return <Loading />;

  return (
    <div>
      {error && <div className="banner banner-error">{error}</div>}

      <div className="card">
        <div className="card-header">Logging</div>
        <LoggingSettings
          settings={settings}
          onToggle={patchSetting}
          saving={saving}
        />
        <hr className="settings-divider" />
        <div className={`toggle-row settings-toggle-mt${settings.disable_all_logging ? " toggle-row-greyed" : ""}`}>
          <div className="toggle-label">
            <span>Audit log flush interval</span>
            <small>How often to snapshot the audit log to disk. "Never" keeps the log in-memory only.</small>
          </div>
          <select
            className="input input-auto"
            value={settings.audit_flush_interval}
            disabled={saving || settings.disable_all_logging}
            onChange={(e) => patchSetting("audit_flush_interval", Number(e.target.value))}
          >
            <option value={0}>Never</option>
            <option value={5}>Every 5 minutes</option>
            <option value={10}>Every 10 minutes</option>
            <option value={15}>Every 15 minutes</option>
            <option value={30}>Every 30 minutes</option>
            <option value={60}>Every 60 minutes</option>
          </select>
        </div>
        <div className={`toggle-row${settings.disable_all_logging ? " toggle-row-greyed" : ""}`}>
          <div className="toggle-label">
            <span>Maximum log entries</span>
            <small>Capacity of the in-memory buffer and the on-disk snapshot. Reducing this trims the oldest entries immediately.</small>
          </div>
          <select
            className="input input-auto"
            value={settings.audit_log_maxlen}
            disabled={saving || settings.disable_all_logging}
            onChange={(e) => patchSetting("audit_log_maxlen", Number(e.target.value))}
          >
            <option value={100}>100</option>
            <option value={1000}>1,000</option>
            <option value={5000}>5,000</option>
            <option value={10000}>10,000</option>
          </select>
        </div>
      </div>

      <div className="card">
        <div className="card-header">Notifications</div>
        <NotificationSettings
          settings={settings}
          onToggle={patchSetting}
          saving={saving}
        />
      </div>

      <div className="card">
        <div className="card-header">Emergency Kill Switch</div>
        <KillSwitch
          settings={settings}
          onToggle={(value) => patchSetting("kill_switch", value)}
          saving={saving}
        />
      </div>

      <div className="card">
        <div className="card-header">Integration Info</div>
        <div className="settings-info-list">
          <div><strong>Version:</strong> {atmVersion ?? "..."}</div>
          <div><strong>Minimum HA version:</strong> {minHaVersion ?? "..."}</div>
          <div>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer"
              className="settings-info-link">
              GitHub repository
            </a>
          </div>
          <div className="settings-info-note">
            ATM configuration is stored in <code>.storage/atm.json</code> and is included in all HA full backups and partial backups of the <code>.storage</code> directory.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header settings-danger-header">
          Data Management
        </div>
        <p className="clear-perms-body">
          Permanently deletes all active tokens, archived records, permission trees, capability flags, settings, the in-memory audit log, and the on-disk audit log snapshot. All tokens are immediately invalidated.
        </p>
        <button
          className="btn btn-danger"
          onClick={() => setShowWipe(true)}
        >
          Wipe All ATM Data
        </button>
      </div>

      {showWipe && (
        <WipeConfirmModal
          onWiped={handleWiped}
          onClose={() => setShowWipe(false)}
        />
      )}

      <div className="settings-version">
        js build {JS_BUILD}
      </div>
    </div>
  );
}
