import React, { useEffect, useState } from "react";
import type { GlobalSettings } from "../types";
import { api } from "../api";
import { LoggingSettings } from "../components/LoggingSettings";
import { NotificationSettings } from "../components/NotificationSettings";
import { KillSwitch } from "../components/KillSwitch";
import { WipeConfirmModal } from "../components/WipeConfirmModal";
import { Loading } from "../index";

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

  useEffect(() => {
    api.getInfo().then((info) => setAtmVersion(info.version)).catch(() => {});
  }, []);

  async function patchSetting(key: keyof GlobalSettings, value: boolean) {
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
        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
          <div><strong>Version:</strong> {atmVersion}</div>
          <div><strong>Minimum HA version:</strong> 2024.1.0</div>
          <div>
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer"
              style={{ color: "var(--primary-color, #03a9f4)" }}>
              GitHub repository
            </a>
          </div>
          <div style={{ fontSize: 13, color: "var(--secondary-text-color, #9e9e9e)" }}>
            ATM configuration is stored in <code>.storage/atm.json</code> and is included in all HA full backups and partial backups of the <code>.storage</code> directory.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header" style={{ color: "var(--error-color, #f44336)" }}>
          Data Management
        </div>
        <p style={{ fontSize: 13, marginTop: 0 }}>
          Permanently deletes all active tokens, archived records, permission trees, capability flags, settings, and the in-memory audit log. All tokens are immediately invalidated.
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
    </div>
  );
}
