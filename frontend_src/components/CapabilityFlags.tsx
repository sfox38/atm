import React from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

interface FlagDef {
  key: keyof Pick<TokenRecord, "allow_restart" | "allow_automation_write" | "allow_script_write" | "allow_config_read" | "allow_template_render" | "allow_service_response" | "allow_broadcast">;
  label: string;
  description: string;
  alwaysShown?: boolean;
  danger?: boolean;
  confirmWarning?: string;
  confirmAck?: string;
}

const FLAGS: FlagDef[] = [
  {
    key: "allow_restart",
    label: "Allow HA restart/stop",
    description: "Permits homeassistant.restart and homeassistant.stop service calls. Evaluated even in pass-through mode.",
    alwaysShown: true,
  },
  {
    key: "allow_automation_write",
    label: "Allow automation write",
    description: "Permits creating, editing, and deleting automations via MCP. Automation payloads are not validated against this token's entity scope - enable only for trusted clients.",
    alwaysShown: true,
    confirmWarning: "Automation payloads are not validated against this token's entity scope. A client with this flag enabled can create automations that control any entity in Home Assistant, regardless of what this token is permitted to access directly. This effectively grants broader system access than the token's entity permissions suggest.",
    confirmAck: "I understand that automation write bypasses entity-level access controls",
  },
  {
    key: "allow_script_write",
    label: "Allow script write",
    description: "Permits creating, editing, and deleting scripts via MCP. Script payloads are not validated against this token's entity scope - enable only for trusted clients.",
    alwaysShown: true,
    confirmWarning: "Script payloads are not validated against this token's entity scope. A client with this flag enabled can create scripts that control any entity in Home Assistant, regardless of what this token is permitted to access directly.",
    confirmAck: "I understand that script write bypasses entity-level access controls",
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
    if (token.pass_through && !flag.alwaysShown) return;
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
      {error && <div className="banner banner-error" style={{ marginBottom: 8 }}>{error}</div>}

      {pendingFlag && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 className="modal-title">Enable {pendingFlag.label}?</h3>
            <div className="amber-block">
              <p><strong>This is an elevated-trust capability.</strong> {pendingFlag.confirmWarning}</p>
            </div>
            <label className="checkbox-row" style={{ marginTop: 12 }}>
              <input
                type="checkbox"
                checked={ackChecked}
                onChange={(e) => setAckChecked(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--warning-color, #ff9800)", cursor: "pointer" }}
              />
              <span>{pendingFlag.confirmAck}</span>
            </label>
            <div className="modal-actions">
              <button
                className="btn btn-primary"
                onClick={handleConfirm}
                disabled={!ackChecked || saving === pendingKey}
                style={{ background: "var(--warning-color, #ff9800)" }}
              >
                {saving === pendingKey ? "Enabling..." : "Enable"}
              </button>
              <button className="btn btn-text" onClick={handleCancel}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {FLAGS.map((flag) => {
        const { key, label, description, alwaysShown, danger } = flag;
        const greyedOut = token.pass_through && !alwaysShown;
        const value = token[key] as boolean;
        return (
          <div
            key={key}
            className="toggle-row"
            style={{ opacity: greyedOut ? 0.5 : 1 }}
            title={greyedOut ? "Not evaluated in pass-through mode" : undefined}
          >
            <div className="toggle-label">
              <span style={danger ? { color: "var(--warning-color, #ff9800)" } : undefined}>{label}</span>
              <small>{description}</small>
            </div>
            <label style={{ display: "flex", alignItems: "center", cursor: greyedOut ? "not-allowed" : "pointer" }}>
              <input
                type="checkbox"
                checked={value}
                disabled={saving === key || greyedOut}
                onChange={() => handleToggle(flag, value)}
                style={{ width: 18, height: 18, accentColor: danger ? "var(--warning-color, #ff9800)" : "var(--primary-color, #03a9f4)", cursor: "inherit" }}
              />
            </label>
          </div>
        );
      })}
    </div>
  );
}
