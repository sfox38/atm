import React from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

interface FlagDef {
  key: keyof Pick<TokenRecord, "allow_restart" | "allow_physical_control" | "allow_automation_write" | "allow_script_write" | "allow_log_read" | "allow_config_read" | "allow_template_render" | "allow_service_response" | "allow_broadcast" | "use_assist_exposure">;
  label: string;
  description: string;
  alwaysShown?: boolean;
  passThoughOnly?: boolean;
  danger?: boolean;
  confirmWarning?: string;
  confirmAck?: string;
}

const FLAGS: FlagDef[] = [
  {
    key: "allow_restart",
    label: "Allow HA restart/stop",
    description: "Permits the homeassistant.restart and homeassistant.stop service calls.",
    alwaysShown: true,
  },
  {
    key: "allow_physical_control",
    label: "Allow physical control",
    description: "Permits lock, alarm, and cover mutation services (e.g. lock.unlock, alarm_control_panel.alarm_disarm, cover.open_cover).",
    alwaysShown: true,
    confirmWarning: "A client with this flag enabled can lock and unlock doors, arm and disarm alarms, and open and close covers. Only enable this for clients you fully trust.",
    confirmAck: "I understand this token will be able to control locks, alarms, and covers",
  },
  {
    key: "allow_automation_write",
    label: "Allow automation write",
    description: "Permits creating, editing, and deleting automations via MCP. A client with this flag can reference any entity in Home Assistant, not just those in this token's scope.",
    alwaysShown: true,
    confirmWarning: "Automation write bypasses this token's entity permissions. A client with this flag enabled can create automations that reference any entity in Home Assistant, regardless of what the token can access directly. Enable only for clients you fully control.",
    confirmAck: "I understand that automation write bypasses entity-level access controls",
  },
  {
    key: "allow_script_write",
    label: "Allow script write",
    description: "Permits creating, editing, and deleting scripts via MCP. A client with this flag can reference any entity in Home Assistant, not just those in this token's scope.",
    alwaysShown: true,
    confirmWarning: "Script write bypasses this token's entity permissions. A client with this flag enabled can create scripts that reference any entity in Home Assistant, regardless of what the token can access directly. Enable only for clients you fully control.",
    confirmAck: "I understand that script write bypasses entity-level access controls",
  },
  {
    key: "allow_log_read",
    label: "Allow log read",
    description: "Permits reading Home Assistant system log entries. Logs may contain IP addresses and internal system details.",
    alwaysShown: true,
  },
  {
    key: "allow_config_read",
    label: "Allow config read",
    description: "Permits reading HA configuration data.",
  },
  {
    key: "allow_template_render",
    label: "Allow template render",
    description: "Permits rendering Jinja2 templates via the template endpoint.",
  },
  {
    key: "allow_service_response",
    label: "Allow service response data",
    description: "When enabled, service calls return response data for services that support it (e.g. conversation.process).",
  },
  {
    key: "allow_broadcast",
    label: "Allow broadcast",
    description: "Permits the HassBroadcast tool to announce messages through assist satellite devices.",
  },
  {
    key: "use_assist_exposure",
    label: "Use HA Assist entity scope",
    description: "Limits entity access to entities exposed in HA's Assist settings, matching native HA MCP server behaviour. Applies to Pass Through tokens only.",
    passThoughOnly: true,
    alwaysShown: true,
  },
];

export function CapabilityFlags({ token, onUpdate }: Props) {
  const [saving, setSaving] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingKey, setPendingKey] = React.useState<string | null>(null);
  const [ackChecked, setAckChecked] = React.useState(false);

  async function applyToggle(key: string, newValue: boolean) {
    setSaving(key);
    setError(null);
    try {
      const body: PatchTokenBody = { [key]: newValue };
      const updated = await api.patchToken(token.id, body);
      onUpdate(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(null);
    }
  }

  function handleToggle(flag: FlagDef, currentValue: boolean) {
    if (token.pass_through && !flag.alwaysShown && !flag.passThoughOnly) return;
    if (!currentValue && flag.confirmWarning) {
      setPendingKey(flag.key);
      setAckChecked(false);
    } else {
      applyToggle(flag.key, !currentValue);
    }
  }

  function handleConfirm() {
    if (!pendingKey || !ackChecked) return;
    applyToggle(pendingKey, true);
    setPendingKey(null);
    setAckChecked(false);
  }

  function handleCancel() {
    setPendingKey(null);
    setAckChecked(false);
  }

  const pendingFlag = FLAGS.find((f) => f.key === pendingKey) ?? null;

  return (
    <div>
      {error && <div className="banner banner-error mb-8">{error}</div>}

      {pendingFlag && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 className="modal-title">Enable {pendingFlag.label}?</h3>
            <div className="amber-block">
              <p><strong>This is an elevated-trust capability.</strong> {pendingFlag.confirmWarning}</p>
            </div>
            <label className="checkbox-row mt-12">
              <input
                type="checkbox"
                checked={ackChecked}
                onChange={(e) => setAckChecked(e.target.checked)}
                className="checkbox-warning"
              />
              <span>{pendingFlag.confirmAck}</span>
            </label>
            <div className="modal-actions">
              <button
                className="btn btn-primary btn-warning"
                onClick={handleConfirm}
                disabled={!ackChecked || saving === pendingKey}
              >
                {saving === pendingKey ? "Enabling..." : "Enable"}
              </button>
              <button className="btn btn-text" onClick={handleCancel}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {FLAGS.map((flag) => {
        const { key, label, description, alwaysShown, passThoughOnly, danger } = flag;
        if (passThoughOnly && !token.pass_through) return null;
        const greyedOut = token.pass_through && !alwaysShown && !passThoughOnly;
        if (greyedOut) return null;
        const value = (token[key] ?? false) as boolean;
        return (
          <div key={key} className="toggle-row">
            <div className="toggle-label">
              <span className={danger ? "text-warning" : undefined}>{label}</span>
              <small>{description}</small>
            </div>
            <label className={`toggle-switch${saving === key ? " disabled" : ""}`}>
              <input
                type="checkbox"
                checked={value}
                disabled={saving === key}
                onChange={() => handleToggle(flag, value)}
              />
              <span className="toggle-switch-track" />
            </label>
          </div>
        );
      })}
    </div>
  );
}
