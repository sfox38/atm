import React from "react";
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

const OUTCOME_LABEL: Record<Outcome, string> = {
  allowed: "Allowed",
  denied: "Denied",
  not_found: "Not Found",
  rate_limited: "Rate Limited",
  not_implemented: "Not Implemented",
};

export function AuditTable({ entries, loading, page, pageSize, onPageChange }: Props) {
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
      <table className="data-table">
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
            <tr key={entry.request_id} className={entry.pass_through ? "pass-through-row" : ""}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>
                {entry.request_id.slice(0, 8)}...
              </td>
              <td style={{ whiteSpace: "nowrap" }}>{formatTs(entry.timestamp)}</td>
              <td>{entry.token_name}</td>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{entry.method}</td>
              <td style={{ fontFamily: "monospace", fontSize: 12, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {entry.resource}
              </td>
              <td>
                <span className={`outcome-${entry.outcome}`}>
                  {OUTCOME_LABEL[entry.outcome] ?? entry.outcome}
                </span>
              </td>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{entry.client_ip}</td>
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
