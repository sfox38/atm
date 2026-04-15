import React, { useState, useEffect, useRef } from "react";
import type { TokenRecord, CreateTokenBody } from "../types";
import { api } from "../api";

const NAME_REGEX = /^[A-Za-z0-9_\-]{3,32}$/;

interface Props {
  existingNames: string[];
  onCreated: (token: TokenRecord, rawToken: string) => void;
  onClose: () => void;
}

type TtlUnit = "minutes" | "hours" | "days" | "weeks" | "none";

function slugify(name: string) {
  return name.toLowerCase().replace(/-/g, "_");
}

function addMinutes(m: number): string {
  const d = new Date(Date.now() + m * 60000);
  return d.toISOString();
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await copyToClipboard(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  return (
    <button className="btn btn-primary" onClick={copy}>
      {copied ? "Copied!" : "Copy to clipboard"}
    </button>
  );
}

interface TokenDisplayProps {
  rawToken: string;
  tokenName: string;
  onClose: () => void;
}

function TokenDisplayModal({ rawToken, tokenName, onClose }: TokenDisplayProps) {
  const [closeEnabled, setCloseEnabled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => setCloseEnabled(true), 3000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3 className="modal-title">Token Created: {tokenName}</h3>
        <div className="amber-block">
          <p><strong>This token will not be shown again.</strong> Copy it now before closing.</p>
        </div>
        <div className="token-display">{rawToken}</div>
        <div className="modal-actions">
          <CopyButton text={rawToken} />
          <button
            className="btn btn-text"
            onClick={onClose}
            disabled={!closeEnabled}
            title={closeEnabled ? undefined : "Wait 3 seconds before closing"}
          >
            {closeEnabled ? "Close" : "Close (3s)"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function TokenCreateModal({ existingNames, onCreated, onClose }: Props) {
  const [name, setName] = useState("");
  const [ttlUnit, setTtlUnit] = useState<TtlUnit>("none");
  const [ttlValue, setTtlValue] = useState("24");
  const [passThrough, setPassThrough] = useState(false);
  const [ptConfirmed, setPtConfirmed] = useState(false);
  const [rateLimitRequests, setRateLimitRequests] = useState("60");
  const [rateLimitBurst, setRateLimitBurst] = useState("10");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdToken, setCreatedToken] = useState<{ record: TokenRecord; raw: string } | null>(null);

  const nameError = (() => {
    if (!name) return null;
    if (!NAME_REGEX.test(name)) return "Name must be 3-32 characters: letters, digits, _ or -.";
    const slug = slugify(name);
    if (existingNames.some((n) => slugify(n) === slug)) return "A token with this name (or equivalent slug) already exists.";
    return null;
  })();

  const reqNum = parseInt(rateLimitRequests, 10);
  const burstDisabled = isNaN(reqNum) || reqNum === 0;

  const canSubmit =
    name.length >= 3 &&
    !nameError &&
    (!passThrough || ptConfirmed) &&
    !saving;

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      let expiresAt: string | undefined;
      if (ttlUnit !== "none") {
        const n = parseInt(ttlValue, 10);
        const minutes =
          ttlUnit === "minutes" ? n :
          ttlUnit === "hours" ? n * 60 :
          ttlUnit === "days" ? n * 60 * 24 :
          n * 60 * 24 * 7;
        expiresAt = addMinutes(minutes);
      }
      const burstNum = burstDisabled ? 0 : parseInt(rateLimitBurst, 10);
      const body: CreateTokenBody = {
        name,
        expires_at: expiresAt,
        pass_through: passThrough,
        confirm_pass_through: passThrough ? true : undefined,
        rate_limit_requests: parseInt(rateLimitRequests, 10) || 0,
        rate_limit_burst: burstNum,
      };
      const resp = await api.createToken(body);
      const { token: rawToken, ...record } = resp;
      setCreatedToken({ record, raw: rawToken });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create token.");
    } finally {
      setSaving(false);
    }
  }

  if (createdToken) {
    return (
      <TokenDisplayModal
        rawToken={createdToken.raw}
        tokenName={createdToken.record.name}
        onClose={() => {
          onCreated(createdToken.record, createdToken.raw);
          onClose();
        }}
      />
    );
  }

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3 className="modal-title">Create Token</h3>

        <div className="field">
          <label>Name (required)</label>
          <input
            className={`input${nameError ? " error" : ""}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my_token"
            maxLength={32}
            autoFocus
          />
          {nameError && <span className="field-error">{nameError}</span>}
        </div>

        <div className="field">
          <label>Expiry</label>
          <div style={{ display: "flex", gap: 8 }}>
            <select
              className="input"
              value={ttlUnit}
              onChange={(e) => setTtlUnit(e.target.value as TtlUnit)}
              style={{ flex: "0 0 auto", width: "auto" }}
            >
              <option value="none">No expiry</option>
              <option value="minutes">Minutes</option>
              <option value="hours">Hours</option>
              <option value="days">Days</option>
              <option value="weeks">Weeks</option>
            </select>
            {ttlUnit !== "none" && (
              <input
                className="input"
                type="number"
                min={1}
                value={ttlValue}
                onChange={(e) => setTtlValue(e.target.value)}
                style={{ width: 80 }}
              />
            )}
          </div>
        </div>

        <div className="toggle-row">
          <div className="toggle-label">
            <span>Pass-through mode (Full Access)</span>
            <small>Bypasses all entity and capability checks. Equivalent to a Long-Lived Access Token.</small>
          </div>
          <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={passThrough}
              onChange={(e) => { setPassThrough(e.target.checked); setPtConfirmed(false); }}
              style={{ width: 18, height: 18, accentColor: "var(--warning-color, #ff9800)", cursor: "pointer" }}
            />
          </label>
        </div>

        {passThrough ? (
          <div className="amber-block">
            <p>
              <strong>This token will have unrestricted access to every entity, service, and system operation in Home Assistant.</strong> It is equivalent to a Long-Lived Access Token. Use only for tools you fully control. Revocation and expiry still apply. Works only with HTTP-based MCP clients, not stdio-based ones.
            </p>
            <label className="checkbox-row" style={{ marginTop: 10 }}>
              <input
                type="checkbox"
                checked={ptConfirmed}
                onChange={(e) => setPtConfirmed(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--warning-color, #ff9800)", cursor: "pointer" }}
              />
              <span>I understand this token has full Home Assistant access</span>
            </label>
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <div className="field" style={{ margin: 0, flex: 1 }}>
                <label>Requests per minute (0 = disabled)</label>
                <input
                  className="input"
                  type="number"
                  min={0}
                  value={rateLimitRequests}
                  onChange={(e) => setRateLimitRequests(e.target.value)}
                />
              </div>
              <div className="field" style={{ margin: 0, flex: 1 }}>
                <label>Burst per second</label>
                <input
                  className="input"
                  type="number"
                  min={0}
                  value={burstDisabled ? "0" : rateLimitBurst}
                  disabled={burstDisabled}
                  onChange={(e) => setRateLimitBurst(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {error && <div className="banner banner-error" style={{ marginTop: 12 }}>{error}</div>}

        <div className="modal-actions">
          <button className="btn btn-text" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={!canSubmit}>
            {saving ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
