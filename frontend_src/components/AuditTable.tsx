import React, { useState } from "react";
import type { AuditEntry, Outcome } from "../types";

interface Props {
  entries: AuditEntry[];
  loading?: boolean;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

function formatTs(iso: string): string {
  return new Date(iso).toLocaleString();
}

function formatTsShort(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const OUTCOME_LABEL: Record<Outcome, string> = {
  allowed: "Allowed",
  denied: "Denied",
  not_found: "Not Found",
  rate_limited: "Rate Limited",
  not_implemented: "Not Implemented",
};

const OUTCOME_CLASS: Record<Outcome, string> = {
  allowed: "outcome-allowed",
  denied: "outcome-denied",
  not_found: "outcome-not_found",
  rate_limited: "outcome-rate_limited",
  not_implemented: "outcome-not_implemented",
};

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 8, padding: "5px 0", borderBottom: "1px solid var(--divider-color, #e0e0e0)" }}>
      <span style={{ width: 88, flexShrink: 0, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--secondary-text-color, #9e9e9e)", paddingTop: 1 }}>{label}</span>
      <span style={{ fontSize: 13, wordBreak: "break-all", fontFamily: mono ? "monospace" : undefined }}>{value}</span>
    </div>
  );
}

function EntryDetailModal({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title" style={{ marginBottom: 12 }}>Audit Entry</h3>
        <DetailRow label="Time" value={formatTs(entry.timestamp)} />
        <DetailRow label="Token" value={entry.token_name} />
        <DetailRow label="Mode" value={entry.pass_through ? "Pass Through" : "Scoped"} />
        <DetailRow label="Method" value={entry.method} mono />
        <DetailRow label="Resource" value={entry.resource} mono />
        <DetailRow label="Outcome" value={OUTCOME_LABEL[entry.outcome] ?? entry.outcome} />
        <DetailRow label="IP" value={entry.client_ip} mono />
        <DetailRow label="Request ID" value={entry.request_id} mono />
        <div className="modal-actions">
          <button className="btn btn-text" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

export function AuditTable({ entries, loading, page, pageSize, onPageChange }: Props) {
  const [selected, setSelected] = useState<AuditEntry | null>(null);

  if (loading) {
    return <div className="loading-wrap"><div className="spinner" /><span>Loading...</span></div>;
  }

  if (entries.length === 0) {
    return (
      <p style={{ color: "var(--secondary-text-color, #9e9e9e)", fontSize: 13 }}>
        No audit entries found.
      </p>
    );
  }

  const totalPages = Math.ceil(entries.length / pageSize);
  const slice = entries.slice(page * pageSize, page * pageSize + pageSize);

  return (
    <div>
      {selected && <EntryDetailModal entry={selected} onClose={() => setSelected(null)} />}
      <table className="data-table audit-table">
        <thead>
          <tr>
            <th>Request ID</th>
            <th>Time</th>
            <th>Token</th>
            <th>Method</th>
            <th>Resource</th>
            <th>Outcome</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody>
          {slice.map((entry) => (
            <tr
              key={entry.request_id}
              className={`clickable${entry.pass_through ? " pass-through-row" : ""}`}
              onClick={() => setSelected(entry)}
            >
              <td
                style={{ fontFamily: "monospace", fontSize: 11 }}
                title={entry.request_id}
              >
                {entry.request_id.slice(0, 8)}...
              </td>
              <td>
                <span className="audit-time-full">{formatTs(entry.timestamp)}</span>
                <span className="audit-time-short">{formatTsShort(entry.timestamp)}</span>
              </td>
              <td title={entry.token_name}>{entry.token_name.replace(/^(admin):(.+)$/, "$1 ($2)")}</td>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{entry.method}</td>
              <td
                style={{ fontFamily: "monospace", fontSize: 12, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={entry.resource}
              >
                {entry.resource}
              </td>
              <td>
                <span className={OUTCOME_CLASS[entry.outcome]}>
                  {OUTCOME_LABEL[entry.outcome] ?? entry.outcome}
                </span>
              </td>
              <td
                style={{ fontFamily: "monospace", fontSize: 12 }}
                title={entry.client_ip}
              >
                {entry.client_ip}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="pagination">
          <button
            className="btn btn-text btn-sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page === 0}
          >
            Prev
          </button>
          <span>Page {page + 1} of {totalPages}</span>
          <button
            className="btn btn-text btn-sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages - 1}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
