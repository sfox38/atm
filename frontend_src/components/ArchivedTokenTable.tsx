import React, { useState } from "react";
import type { ArchivedTokenRecord } from "../types";
import { api } from "../api";

interface Props {
  tokens: ArchivedTokenRecord[];
  onDeleted: (id: string) => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString();
}

export function ArchivedTokenTable({ tokens, onDeleted }: Props) {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function deletePermanently(id: string) {
    setDeleting(id);
    setError(null);
    try {
      await api.deleteArchivedToken(id);
      onDeleted(id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setDeleting(null);
      setConfirmId(null);
    }
  }

  if (tokens.length === 0) {
    return <p className="archived-empty">No archived tokens.</p>;
  }

  return (
    <div>
      {error && <div className="banner banner-error mb-8">{error}</div>}
      <table className="data-table archived-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Created</th>
            <th>Archived On</th>
            <th>Last Used</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {tokens.map((t) => {
            const status = t.revoked ? "Revoked" : "Expired";
            return (
              <tr
                key={t.id}
                className={t.pass_through ? "pass-through-row" : ""}
              >
                <td>{t.name}</td>
                <td>
                  {t.pass_through ? (
                    <span className="badge badge-amber">Pass Through</span>
                  ) : (
                    <span className="badge badge-blue">Scoped</span>
                  )}
                </td>
                <td>
                  <span className={`badge ${status === "Revoked" ? "badge-red" : "badge-grey"}`}>
                    {status}
                  </span>
                </td>
                <td>{formatDate(t.created_at)}</td>
                <td>{formatDate(t.revoked_at)}</td>
                <td>{formatDate(t.last_used_at)}</td>
                <td>
                  {confirmId === t.id ? (
                    <span className="row-actions">
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => deletePermanently(t.id)}
                        disabled={deleting === t.id}
                      >
                        {deleting === t.id ? "..." : "Confirm delete"}
                      </button>
                      <button
                        className="btn btn-text btn-sm"
                        onClick={() => setConfirmId(null)}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => setConfirmId(t.id)}
                    >
                      Delete permanently
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
