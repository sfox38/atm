import React, { useState, useEffect, useCallback, useRef } from "react";
import type { TokenRecord, PatchTokenBody } from "../types";
import { api } from "../api";
import { Loading, ErrorMsg } from "../index";
import { CapabilityFlags } from "../components/CapabilityFlags";
import { RateLimitConfig } from "../components/RateLimitConfig";
import { PassThroughNotice } from "../components/PassThroughNotice";
import { EntityTree } from "../components/EntityTree";
import { PermissionSummary } from "../components/PermissionSummary";
import { PermissionSimulator } from "../components/PermissionSimulator";
import { AreaPicker } from "../components/AreaPicker";

interface Props {
  tokenId: string;
  onBack: () => void;
  onRefresh?: () => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString();
}

function tokenStatus(t: TokenRecord): string {
  if (t.revoked) return "Revoked";
  if (t.expires_at && new Date(t.expires_at) <= new Date()) return "Expired";
  return "Active";
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

function RotatedTokenModal({ rawToken, tokenName, onClose }: { rawToken: string; tokenName: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [closeEnabled, setCloseEnabled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => setCloseEnabled(true), 3000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  async function copy() {
    await copyToClipboard(rawToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3 className="modal-title">Token Rotated: {tokenName}</h3>
        <div className="amber-block">
          <p><strong>The old token value is now invalid.</strong> Copy the new token before closing. It will not be shown again.</p>
        </div>
        <div className="token-display">{rawToken}</div>
        <div className="modal-actions">
          <button className="btn btn-primary" onClick={copy}>{copied ? "Copied!" : "Copy to clipboard"}</button>
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

export function TokenDetailView({ tokenId, onBack, onRefresh }: Props) {
  const [token, setToken] = useState<TokenRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [showRevoke, setShowRevoke] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [showRotateConfirm, setShowRotateConfirm] = useState(false);
  const [rotatedRawToken, setRotatedRawToken] = useState<string | null>(null);
  const [showAreaPicker, setShowAreaPicker] = useState(false);
  const [entityTree, setEntityTree] = useState<import("../types").EntityTree | null>(null);
  const [ptToggling, setPtToggling] = useState(false);
  const [ptConfirmBox, setPtConfirmBox] = useState(false);
  const [ptConfirmed, setPtConfirmed] = useState(false);
  const [selectedEntityId, setSelectedEntityId] = useState("");
  const [permissionsVersion, setPermissionsVersion] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getToken(tokenId);
      setToken(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load token.");
    } finally {
      setLoading(false);
    }
  }, [tokenId]);

  useEffect(() => { load(); }, [load]);

  // Pre-fetch entity tree for AreaPicker
  useEffect(() => {
    api.getEntityTree().then(setEntityTree).catch(() => null);
  }, []);

  async function revoke() {
    setRevoking(true);
    try {
      await api.revokeToken(tokenId);
      onBack();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to revoke token.");
      setRevoking(false);
    }
  }

  async function rotate() {
    setRotating(true);
    try {
      const resp = await api.rotateToken(tokenId);
      const { token: rawToken } = resp as { token: string };
      setRotatedRawToken(rawToken);
      setShowRotateConfirm(false);
      onRefresh?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to rotate token.");
    } finally {
      setRotating(false);
    }
  }

  async function enablePassThrough() {
    if (!ptConfirmed) return;
    setPtToggling(true);
    try {
      const body: PatchTokenBody = { pass_through: true, confirm_pass_through: true };
      const updated = await api.patchToken(tokenId, body);
      setToken(updated);
      setPtConfirmBox(false);
      setPtConfirmed(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to enable pass-through.");
    } finally {
      setPtToggling(false);
    }
  }

  if (loading) return <Loading />;
  if (error && !token) return <div><button className="btn btn-text" onClick={onBack}>Back</button><ErrorMsg msg={error} /></div>;
  if (!token) return null;

  if (rotatedRawToken) {
    return <RotatedTokenModal rawToken={rotatedRawToken} tokenName={token.name} onClose={() => setRotatedRawToken(null)} />;
  }

  const status = tokenStatus(token);
  const statusClass = status === "Active" ? "badge-green" : status === "Expired" ? "badge-grey" : "badge-red";

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <button className="btn btn-text" onClick={onBack} style={{ textTransform: "none", letterSpacing: 0 }}>
          Back to token list
        </button>
      </div>

      {error && <ErrorMsg msg={error} />}

      {token.pass_through && (
        <div className="pass-through-header-banner">
          <p>
            <strong style={{ color: "var(--warning-color, #ff9800)" }}>This is a Full Access token.</strong> It has unrestricted access to all Home Assistant entities and services. No entity scoping or capability restrictions apply. Only revocation, expiry, rate limiting, and audit logging are active.
          </p>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span>{token.name}</span>
          <div style={{ display: "flex", gap: 8 }}>
            {!showRotateConfirm && !showRevoke && (
              <button
                className="btn btn-text btn-sm"
                onClick={() => setShowRotateConfirm(true)}
              >
                Rotate
              </button>
            )}
            {showRotateConfirm && (
              <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: 13 }}>Old token invalidated immediately. Continue?</span>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={rotate}
                  disabled={rotating}
                >
                  {rotating ? "Rotating..." : "Confirm"}
                </button>
                <button className="btn btn-text btn-sm" onClick={() => setShowRotateConfirm(false)}>Cancel</button>
              </span>
            )}
            {!showRotateConfirm && (
              <>
                {!showRevoke ? (
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => setShowRevoke(true)}
                  >
                    Revoke
                  </button>
                ) : (
                  <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <span style={{ fontSize: 13 }}>Revoke token?</span>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={revoke}
                      disabled={revoking}
                    >
                      {revoking ? "Revoking..." : "Confirm"}
                    </button>
                    <button className="btn btn-text btn-sm" onClick={() => setShowRevoke(false)}>Cancel</button>
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        <div className="stat-row">
          <div className="stat-item">
            <span className="stat-label">Status</span>
            <span className="stat-value"><span className={`badge ${statusClass}`}>{status}</span></span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Mode</span>
            <span className="stat-value">
              {token.pass_through
                ? <span className="badge badge-amber">Full Access</span>
                : <span className="badge badge-blue">Scoped</span>}
            </span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Created</span>
            <span className="stat-value" style={{ fontSize: 13 }} title={token.created_at ? new Date(token.created_at).toLocaleString() : undefined}>{formatDate(token.created_at)}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Last Updated</span>
            <span className="stat-value" style={{ fontSize: 13 }} title={token.updated_at ? new Date(token.updated_at).toLocaleString() : undefined}>{formatDate(token.updated_at)}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Expires</span>
            <span className="stat-value" style={{ fontSize: 13 }}>{formatDate(token.expires_at)}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Last used</span>
            <span className="stat-value" style={{ fontSize: 13 }}>{formatDate(token.last_used_at)}</span>
          </div>
        </div>

        {!token.pass_through && (
          <div>
            {!ptConfirmBox ? (
              <button
                className="btn btn-text btn-sm"
                style={{ color: "var(--warning-color, #ff9800)" }}
                onClick={() => setPtConfirmBox(true)}
              >
                Enable pass-through mode
              </button>
            ) : (
              <div className="amber-block">
                <p>
                  <strong>Enabling pass-through gives this token full unrestricted access.</strong> It is equivalent to a Long-Lived Access Token.
                </p>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={ptConfirmed}
                    onChange={(e) => setPtConfirmed(e.target.checked)}
                    style={{ width: 18, height: 18, accentColor: "var(--warning-color, #ff9800)", cursor: "pointer" }}
                  />
                  <span>I understand this token will have full Home Assistant access</span>
                </label>
                <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                  <button
                    className="btn btn-primary"
                    onClick={enablePassThrough}
                    disabled={!ptConfirmed || ptToggling}
                  >
                    {ptToggling ? "Enabling..." : "Enable Pass-Through"}
                  </button>
                  <button className="btn btn-text" onClick={() => { setPtConfirmBox(false); setPtConfirmed(false); }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="two-col">
        <div>
          <div className="card">
            <div className="card-header">Capability Flags</div>
            <CapabilityFlags token={token} onUpdate={setToken} />
          </div>
          <div className="card">
            <div className="card-header">Rate Limiting</div>
            <RateLimitConfig token={token} onUpdate={setToken} />
          </div>
          {!token.pass_through && (
            <div className="card">
              <div className="card-header">Effective Permission Simulator</div>
              <PermissionSimulator
                tokenId={tokenId}
                externalEntityId={selectedEntityId || undefined}
                triggerVersion={permissionsVersion}
              />
            </div>
          )}
          {!token.pass_through && (
            <div className="card">
              <div className="card-header">Permission Summary</div>
              <PermissionSummary
                permissions={token.permissions}
                entityTree={entityTree}
                onEntityClick={setSelectedEntityId}
              />
            </div>
          )}
        </div>

        <div>
          {token.pass_through ? (
            <div className="card">
              <div className="card-header">Entity Permissions</div>
              <PassThroughNotice token={token} onUpdate={setToken} />
            </div>
          ) : (
            <div className="card">
              <div className="card-header">
                <span>Entity Permissions</span>
                {entityTree && (
                  <button
                    className="btn btn-text btn-sm"
                    onClick={() => setShowAreaPicker(true)}
                  >
                    Select by Area
                  </button>
                )}
              </div>
              <EntityTree
                tokenId={tokenId}
                permissions={token.permissions}
                onPermissionsChange={(tree) => {
                  setToken({ ...token, permissions: tree });
                  setPermissionsVersion((v) => v + 1);
                }}
                onEntityClick={setSelectedEntityId}
              />
            </div>
          )}
        </div>
      </div>

      {showAreaPicker && entityTree && (
        <AreaPicker
          tokenId={tokenId}
          entityTree={entityTree}
          onDone={() => {
            setShowAreaPicker(false);
            load();
          }}
          onClose={() => setShowAreaPicker(false)}
        />
      )}
    </div>
  );
}
