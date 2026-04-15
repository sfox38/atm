import React, { useState, useEffect, useCallback } from "react";
import type { TokenRecord, ArchivedTokenRecord } from "../types";
import { TokenCreateModal } from "../components/TokenCreateModal";
import { ArchivedTokenTable } from "../components/ArchivedTokenTable";
import { api } from "../api";
import { Loading, ErrorMsg } from "../index";

const MAX_ACTIVE_TOKENS_WARNING = 50;

function relativeTime(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString();
}

function tokenStatus(t: TokenRecord): string {
  if (t.revoked) return "Revoked";
  if (t.expires_at && new Date(t.expires_at) <= new Date()) return "Expired";
  return "Active";
}

interface Props {
  tokens: TokenRecord[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onOpenDetail: (id: string) => void;
  showArchived: boolean;
  onShowArchivedChange: (v: boolean) => void;
}

export function TokenListView({ tokens, loading, error, onRefresh, onOpenDetail, showArchived, onShowArchivedChange }: Props) {
  const [filter, setFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [archived, setArchived] = useState<ArchivedTokenRecord[] | null>(null);
  const [archivedLoading, setArchivedLoading] = useState(false);

  const refreshArchived = useCallback(async () => {
    setArchivedLoading(true);
    try {
      setArchived(await api.listArchivedTokens());
    } catch {
      setArchived([]);
    } finally {
      setArchivedLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showArchived) refreshArchived();
  }, [showArchived, refreshArchived]);

  const filtered = tokens.filter((t) => {
    const q = filter.toLowerCase();
    if (!q) return true;
    return t.name.toLowerCase().includes(q) || tokenStatus(t).toLowerCase().includes(q);
  });

  function handleCreated(record: TokenRecord) {
    onRefresh();
    setShowCreate(false);
    onOpenDetail(record.id);
  }

  function handleArchivedDeleted(id: string) {
    setArchived((prev) => prev?.filter((t) => t.id !== id) ?? null);
  }

  return (
    <div>
      {tokens.length >= MAX_ACTIVE_TOKENS_WARNING && (
        <div className="banner banner-warn">
          You have reached the recommended maximum of {MAX_ACTIVE_TOKENS_WARNING} active tokens. Consider revoking unused tokens.
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span>Tokens ({tokens.length})</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-text btn-sm" onClick={() => { onRefresh(); if (showArchived) refreshArchived(); }}>Refresh</button>
            <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
              Create Token
            </button>
          </div>
        </div>

        <div className="filter-row">
          <input
            className="input"
            placeholder="Filter by name or status..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorMsg msg={error} />
        ) : (
          <table className="data-table token-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last Updated</th>
                <th>Expires</th>
                <th>Last Used</th>
                <th>Rate Limit</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} style={{ textAlign: "center", color: "var(--secondary-text-color, #9e9e9e)" }}>
                    {filter ? "No tokens match the filter." : "No tokens yet. Create one to get started."}
                  </td>
                </tr>
              )}
              {filtered.map((t) => {
                const status = tokenStatus(t);
                const statusClass = status === "Active" ? "badge-green" : status === "Expired" ? "badge-grey" : "badge-red";
                return (
                  <tr
                    key={t.id}
                    className={`clickable${t.pass_through ? " pass-through-row" : ""}`}
                    onClick={() => onOpenDetail(t.id)}
                  >
                    <td style={{ fontWeight: 500 }}>{t.name}</td>
                    <td>
                      {t.pass_through ? (
                        <span className="badge badge-amber">Full Access</span>
                      ) : (
                        <span className="badge badge-blue">Scoped</span>
                      )}
                    </td>
                    <td><span className={`badge ${statusClass}`}>{status}</span></td>
                    <td title={t.created_at ? new Date(t.created_at).toLocaleString() : undefined}>{formatDate(t.created_at)}</td>
                    <td title={t.updated_at ? new Date(t.updated_at).toLocaleString() : undefined}>{relativeTime(t.updated_at)}</td>
                    <td>{formatDate(t.expires_at)}</td>
                    <td>{relativeTime(t.last_used_at)}</td>
                    <td>
                      {t.rate_limit_requests === 0
                        ? "Disabled"
                        : `${t.rate_limit_requests}/min`}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: 4 }}>
                        <button
                          className="btn btn-text btn-sm"
                          onClick={() => onOpenDetail(t.id)}
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <button
          className="btn btn-text"
          onClick={() => onShowArchivedChange(!showArchived)}
          style={{ textTransform: "none", letterSpacing: 0 }}
        >
          {showArchived ? "Hide archived" : "Show archived"}
        </button>
      </div>

      {showArchived && (
        <div className="card">
          <div className="card-header">
            <span>Archived Tokens</span>
          </div>
          {archivedLoading ? (
            <Loading />
          ) : (
            <ArchivedTokenTable
              tokens={archived ?? []}
              onDeleted={handleArchivedDeleted}
            />
          )}
        </div>
      )}

      {showCreate && (
        <TokenCreateModal
          existingNames={tokens.map((t) => t.name)}
          onCreated={handleCreated}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}
