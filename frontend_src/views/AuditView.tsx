import React, { useState, useEffect, useCallback } from "react";
import type { AuditEntry, TokenRecord, Outcome } from "../types";
import { api } from "../api";
import { AuditTable } from "../components/AuditTable";

interface Props {
  tokens: TokenRecord[];
}

const PAGE_SIZE = 100;

export function AuditView({ tokens }: Props) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [tokenFilter, setTokenFilter] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState<Outcome | "">("");
  const [ipFilter, setIpFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAudit({ limit: 500 });
      setEntries(data);
      setPage(0);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = entries.filter((e) => {
    if (tokenFilter && e.token_id !== tokenFilter) return false;
    if (outcomeFilter && e.outcome !== outcomeFilter) return false;
    if (ipFilter && !e.client_ip.includes(ipFilter)) return false;
    if (resourceFilter && !e.resource.toLowerCase().includes(resourceFilter.toLowerCase())) return false;
    return true;
  });

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <span>Audit Log</span>
          <button className="btn btn-text btn-sm" onClick={load}>Refresh</button>
        </div>

        <div className="filter-row">
          <select
            className="input"
            style={{ flex: "0 0 auto", width: "auto" }}
            value={tokenFilter}
            onChange={(e) => { setTokenFilter(e.target.value); setPage(0); }}
          >
            <option value="">All tokens</option>
            {tokens.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <select
            className="input"
            style={{ flex: "0 0 auto", width: "auto" }}
            value={outcomeFilter}
            onChange={(e) => { setOutcomeFilter(e.target.value as Outcome | ""); setPage(0); }}
          >
            <option value="">All outcomes</option>
            <option value="allowed">Allowed</option>
            <option value="denied">Denied</option>
            <option value="not_found">Not Found</option>
            <option value="rate_limited">Rate Limited</option>
          </select>
          <input
            className="input"
            placeholder="Filter by resource..."
            value={resourceFilter}
            onChange={(e) => { setResourceFilter(e.target.value); setPage(0); }}
          />
          <input
            className="input"
            placeholder="Filter by IP..."
            value={ipFilter}
            onChange={(e) => { setIpFilter(e.target.value); setPage(0); }}
          />
        </div>

        <AuditTable
          entries={filtered}
          loading={loading}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
