import React, { useState, useEffect, useCallback } from "react";
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

export function TokenDetailView({ tokenId, onBack }: Props) {
  const [token, setToken] = useState<TokenRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [showRevoke, setShowRevoke] = useState(false);
  const [showAreaPicker, setShowAreaPicker] = useState(false);
  const [entityTree, setEntityTree] = useState<import("../types").EntityTree | null>(null);
  const [ptToggling, setPtToggling] = useState(false);
  const [ptConfirmBox, setPtConfirmBox] = useState(false);
  const [ptConfirmed, setPtConfirmed] = useState(false);

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
            <strong style={{ color: "var(--warning-color, #ff9800)" }}>This is a Full Access token.</strong> It has unrestricted access to all Home Assistant entities and services. No entity scoping or capability restrictions apply. Only revocation, TTL, rate limiting, and audit logging are active.
          </p>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span>{token.name}</span>
          <div style={{ display: "flex", gap: 8 }}>
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
            <span className="stat-value" style={{ fontSize: 13 }}>{formatDate(token.created_at)}</span>
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
                onPermissionsChange={(tree) => setToken({ ...token, permissions: tree })}
              />
            </div>
          )}
        </div>
      </div>

      {!token.pass_through && (
        <>
          <div className="card">
            <div className="card-header">Permission Summary</div>
            <PermissionSummary permissions={token.permissions} entityTree={entityTree} />
          </div>
          <div className="card">
            <div className="card-header">Effective Permission Simulator</div>
            <PermissionSimulator tokenId={tokenId} />
          </div>
        </>
      )}

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
