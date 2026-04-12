import React from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";

interface Props {
  token: TokenRecord;
  onUpdate: (updated: TokenRecord) => void;
}

const FLAGS: {
  key: keyof Pick<TokenRecord, "allow_restart" | "allow_automation_write" | "allow_config_read" | "allow_template_render">;
  label: string;
  description: string;
  alwaysShown?: boolean;
}[] = [
  {
    key: "allow_restart",
    label: "Allow HA restart/stop",
    description: "Permits homeassistant.restart and homeassistant.stop service calls. Evaluated even in pass-through mode.",
    alwaysShown: true,
  },
  {
    key: "allow_automation_write",
    label: "Allow automation write",
    description: "Permits creating and modifying HA automations.",
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
];

export function CapabilityFlags({ token, onUpdate }: Props) {
  const [saving, setSaving] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function toggle(key: string, currentValue: boolean) {
    setSaving(key);
    setError(null);
    try {
      const body: PatchTokenBody = { [key]: !currentValue };
      const updated = await api.patchToken(token.id, body);
      onUpdate(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(null);
    }
  }

  return (
    <div>
      {error && <div className="banner banner-error" style={{ marginBottom: 8 }}>{error}</div>}
      {FLAGS.map(({ key, label, description, alwaysShown }) => {
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
              <span>{label}</span>
              <small>{description}</small>
            </div>
            <label style={{ display: "flex", alignItems: "center", cursor: greyedOut ? "not-allowed" : "pointer" }}>
              <input
                type="checkbox"
                checked={value}
                disabled={saving === key || greyedOut}
                onChange={() => !greyedOut && toggle(key, value)}
                style={{ width: 18, height: 18, accentColor: "var(--primary-color, #03a9f4)", cursor: "inherit" }}
              />
            </label>
          </div>
        );
      })}
    </div>
  );
}
