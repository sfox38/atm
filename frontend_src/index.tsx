import React, { useState, useEffect, useCallback, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { TokenRecord, GlobalSettings } from "./types";
import { TokenListView } from "./views/TokenList";
import { TokenDetailView } from "./views/TokenDetail";
import { AuditView } from "./views/AuditView";
import { SettingsView } from "./views/SettingsView";
import { api, setHass } from "./api";

type Tab = "tokens" | "audit" | "settings";

const HIGH_RISK_DOMAINS = new Set([
  "homeassistant", "recorder", "system_log", "hassio",
  "backup", "notify", "persistent_notification", "mqtt",
]);

export { HIGH_RISK_DOMAINS };

const PANEL_CSS = `
  :host {
    display: block;
    height: 100%;
    position: relative;
    touch-action: pan-y;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    font-size: 14px;
  }
  * { box-sizing: border-box; touch-action: pan-y; }

  .atm-shell {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .atm-header {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 4px;
    background: var(--app-header-background-color, var(--primary-color, #03a9f4));
    color: var(--app-header-text-color, #fff);
    flex-shrink: 0;
  }
  .atm-header-title {
    font-size: 20px;
    font-weight: 400;
    margin-left: 4px;
    color: var(--app-header-text-color, #fff);
  }

  /* Tab bar */
  .atm-tabs {
    display: flex;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    background: var(--card-background-color, #fff);
    padding: 0 16px;
    gap: 0;
    flex-shrink: 0;
  }
  .atm-tab {
    padding: 14px 20px;
    border: none;
    border-bottom: 3px solid transparent;
    background: none;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    transition: color 0.2s, border-color 0.2s;
  }
  .atm-tab:hover {
    color: var(--primary-text-color, #212121);
    background: var(--secondary-background-color, #f5f5f5);
  }
  .atm-tab.active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }

  /* Main content area */
  .atm-content {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    touch-action: pan-y;
  }

  /* Card */
  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.1));
    padding: 16px;
    margin-bottom: 16px;
  }
  .card-header {
    font-size: 16px;
    font-weight: 500;
    margin: 0 0 12px 0;
    color: var(--primary-text-color, #212121);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  /* Buttons */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    transition: background 0.2s, box-shadow 0.2s;
    white-space: nowrap;
  }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-primary {
    background: var(--primary-color, #03a9f4);
    color: #fff;
  }
  .btn-primary:hover:not(:disabled) {
    background: var(--dark-primary-color, #0288d1);
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  }
  .btn-danger {
    background: var(--error-color, #f44336);
    color: #fff;
  }
  .btn-danger:hover:not(:disabled) {
    background: #d32f2f;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  }
  .btn-outline {
    background: transparent;
    color: var(--primary-color, #03a9f4);
    border: 1px solid var(--primary-color, #03a9f4);
  }
  .btn-outline:hover:not(:disabled) {
    background: rgba(3, 169, 244, 0.08);
  }
  .btn-text {
    background: transparent;
    color: var(--primary-color, #03a9f4);
    padding: 6px 8px;
    text-transform: none;
    letter-spacing: 0;
  }
  .btn-text:hover:not(:disabled) {
    background: rgba(3, 169, 244, 0.08);
  }
  .btn-sm { padding: 5px 10px; font-size: 12px; }

  /* Badges */
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }
  .badge-blue { background: rgba(3,169,244,0.15); color: var(--primary-color, #03a9f4); }
  .badge-amber { background: rgba(255,152,0,0.15); color: var(--warning-color, #ff9800); }
  .badge-green { background: rgba(76,175,80,0.15); color: var(--success-color, #4caf50); }
  .badge-red { background: rgba(244,67,54,0.15); color: var(--error-color, #f44336); }
  .badge-grey { background: rgba(0,0,0,0.08); color: var(--secondary-text-color, #727272); }

  /* Tables */
  .data-table {
    width: 100%;
    border-collapse: collapse;
  }
  .data-table th {
    text-align: left;
    padding: 10px 12px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--secondary-text-color, #727272);
    border-bottom: 2px solid var(--divider-color, #e0e0e0);
  }
  .data-table td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    vertical-align: middle;
  }
  .data-table tr:last-child td { border-bottom: none; }
  .data-table tbody tr { transition: background 0.15s; }
  .data-table tbody tr.clickable { cursor: pointer; }
  .data-table tbody tr.clickable:hover { background: var(--secondary-background-color, #f5f5f5); }
  .data-table tbody tr.pass-through-row {
    background: rgba(255, 152, 0, 0.08);
  }
  .data-table tbody tr.pass-through-row:hover {
    background: rgba(255, 152, 0, 0.14);
  }

  /* Inputs */
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .field label {
    font-size: 12px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .input {
    padding: 8px 12px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-size: 14px;
    width: 100%;
    transition: border-color 0.2s;
  }
  .input:focus {
    outline: none;
    border-color: var(--primary-color, #03a9f4);
  }
  .input:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .input.error { border-color: var(--error-color, #f44336); }
  .field-error {
    font-size: 12px;
    color: var(--error-color, #f44336);
  }

  /* Toggle row */
  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .toggle-row:last-child { border-bottom: none; }
  .toggle-label { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
  .toggle-label span { font-size: 14px; }
  .toggle-label small { font-size: 12px; color: var(--secondary-text-color, #727272); word-wrap: break-word; }

  /* Modal overlay */
  .modal-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 16px;
  }
  .modal {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    padding: 24px;
    max-width: 560px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
  }
  .modal-title {
    font-size: 18px;
    font-weight: 500;
    margin: 0 0 20px 0;
  }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 20px;
  }

  /* Warning / amber block */
  .amber-block {
    background: rgba(255,152,0,0.12);
    border: 1px solid var(--warning-color, #ff9800);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
  }
  .amber-block p { margin: 0; color: var(--primary-text-color, #212121); font-size: 13px; line-height: 1.5; }
  .amber-block strong { color: var(--warning-color, #ff9800); }

  /* Pass-through banner (full width in token detail header) */
  .pass-through-header-banner {
    background: rgba(255,152,0,0.12);
    border: 1px solid var(--warning-color, #ff9800);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 16px;
  }
  .pass-through-header-banner p { margin: 4px 0; font-size: 13px; }

  /* Error / info banners */
  .banner {
    padding: 10px 16px;
    border-radius: 6px;
    font-size: 13px;
    margin-bottom: 12px;
  }
  .banner-warn {
    background: rgba(255,152,0,0.12);
    border: 1px solid var(--warning-color, #ff9800);
    color: var(--primary-text-color, #212121);
  }
  .banner-info {
    background: rgba(3,169,244,0.08);
    border: 1px solid var(--primary-color, #03a9f4);
    color: var(--primary-text-color, #212121);
  }
  .banner-error {
    background: rgba(244,67,54,0.08);
    border: 1px solid var(--error-color, #f44336);
    color: var(--error-color, #f44336);
  }

  /* Two-column layout */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  @media (max-width: 900px) {
    .two-col { grid-template-columns: 1fr; }
    .two-col > *:first-child { order: 2; }
    .two-col > *:last-child { order: 1; }
  }
  @media (max-width: 600px) {
    .atm-content { padding: 8px; }
    .card { padding: 12px; }
    .atm-tab { padding: 12px 10px; font-size: 12px; }
    .tree-badge { display: none; }
    .tree-effective { display: none; }
    .tree-hint-link { display: none; }

    /* Token list: responsive table */
    .data-table { display: block; }
    .data-table thead { display: none; }
    .data-table tbody { display: block; }
    .data-table tr {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px 8px;
      padding: 10px 0;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    .data-table tr:last-child { border-bottom: none; }
    .data-table td {
      display: inline-flex;
      align-items: center;
      padding: 1px 0;
      border: none;
      font-size: 13px;
    }
    /* Row 1: name (stretches) + actions (right) */
    .data-table td:nth-child(1) { flex: 1; min-width: 0; font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .data-table td:nth-child(9) { flex-shrink: 0; padding: 0; }
    /* Row 2: mode, status, last used, rate limit */
    .data-table td:nth-child(2),
    .data-table td:nth-child(3) { order: 10; }
    .data-table td:nth-child(7),
    .data-table td:nth-child(8) { order: 10; font-size: 11px; color: var(--secondary-text-color, #9e9e9e); }
    /* Hide date columns */
    .data-table td:nth-child(4),
    .data-table td:nth-child(5),
    .data-table td:nth-child(6) { display: none; }
  }

  /* Permission state colors */
  .state-GREY { color: var(--secondary-text-color, #9e9e9e); }
  .state-YELLOW { color: var(--warning-color, #ff9800); }
  .state-GREEN { color: var(--success-color, #4caf50); }
  .state-RED { color: var(--error-color, #f44336); }

  /* Permission selector [N][R][W][D] */
  .perm-selector {
    display: inline-flex;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px;
    overflow: hidden;
    flex-shrink: 0;
  }
  .perm-btn {
    padding: 3px 7px;
    border: none;
    touch-action: none;
    border-right: 1px solid var(--divider-color, #e0e0e0);
    background: none;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    color: var(--secondary-text-color, #9e9e9e);
    transition: background 0.15s, color 0.15s;
    min-width: 26px;
    text-align: center;
  }
  .perm-btn:last-child { border-right: none; }
  .perm-btn:hover { background: var(--secondary-background-color, #f5f5f5); }
  .perm-btn.active-GREY { background: rgba(0,0,0,0.08); color: var(--secondary-text-color, #9e9e9e); }
  .perm-btn.active-YELLOW { background: rgba(255,152,0,0.2); color: var(--warning-color, #ff9800); }
  .perm-btn.active-GREEN { background: rgba(76,175,80,0.2); color: var(--success-color, #4caf50); }
  .perm-btn.active-RED { background: rgba(244,67,54,0.2); color: var(--error-color, #f44336); }

  /* Entity tree */
  .tree-filter {
    margin-bottom: 12px;
    display: flex;
    gap: 8px;
  }
  .tree-node {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border-radius: 4px;
    transition: background 0.15s;
  }
  .tree-node:hover { background: var(--secondary-background-color, #f5f5f5); }
  .tree-expand {
    width: 20px;
    height: 20px;
    border: none;
    background: none;
    cursor: pointer;
    color: var(--secondary-text-color, #9e9e9e);
    font-size: 10px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 3px;
    padding: 0;
  }
  .tree-expand:hover { background: var(--secondary-background-color, #f5f5f5); }
  .tree-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tree-entity-id { font-size: 12px; color: var(--secondary-text-color, #9e9e9e); }
  .tree-friendly { font-size: 13px; }
  .tree-effective {
    font-size: 11px;
    color: var(--secondary-text-color, #9e9e9e);
    white-space: nowrap;
  }
  .tree-children { padding-left: 20px; }
  .tree-badge {
    font-size: 10px;
    font-weight: 600;
    padding: 1px 5px;
    border-radius: 3px;
    flex-shrink: 0;
  }
  .tree-badge-dynamic { background: rgba(3,169,244,0.1); color: var(--primary-color, #03a9f4); }
  .tree-badge-risk { background: rgba(244,67,54,0.1); color: var(--error-color, #f44336); }
  .tree-badge-ghost { background: rgba(255,152,0,0.1); color: var(--warning-color, #ff9800); }
  .tree-hint-link {
    font-size: 11px;
    color: var(--primary-color, #03a9f4);
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    text-decoration: underline;
    white-space: nowrap;
  }
  .tree-hint-input {
    font-size: 12px;
    padding: 2px 6px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 3px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    width: 120px;
  }
  .tree-hint-input:focus { outline: none; border-color: var(--primary-color, #03a9f4); }

  /* Loading */
  .loading-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px;
    color: var(--secondary-text-color, #9e9e9e);
    gap: 12px;
  }
  .spinner {
    width: 24px;
    height: 24px;
    border: 3px solid var(--divider-color, #e0e0e0);
    border-top-color: var(--primary-color, #03a9f4);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Filter row */
  .filter-row {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
    align-items: center;
  }
  .filter-row .input { flex: 1; min-width: 180px; }

  /* Section header */
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--secondary-text-color, #727272);
  }

  /* Monospace token display */
  .token-display {
    font-family: "Roboto Mono", monospace;
    font-size: 13px;
    background: var(--secondary-background-color, #f5f5f5);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px;
    padding: 12px;
    word-break: break-all;
    user-select: all;
    margin: 12px 0;
  }

  /* Audit table outcome badges */
  .outcome-allowed { color: var(--success-color, #4caf50); font-weight: 500; }
  .outcome-denied { color: var(--error-color, #f44336); font-weight: 500; }
  .outcome-not_found { color: var(--secondary-text-color, #9e9e9e); font-weight: 500; }
  .outcome-rate_limited { color: var(--warning-color, #ff9800); font-weight: 500; }
  .outcome-not_implemented { color: var(--info-color, #2196f3); font-weight: 500; }

  /* Permission summary */
  .perm-summary { font-family: "Roboto Mono", monospace; font-size: 12px; }
  .perm-summary-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 3px 0;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .perm-summary-row:last-child { border-bottom: none; }

  /* Simulator */
  .sim-path {
    font-size: 13px;
    background: var(--secondary-background-color, #f5f5f5);
    border-radius: 6px;
    padding: 10px 14px;
    font-family: "Roboto Mono", monospace;
  }
  .sim-step { margin: 2px 0; }

  /* Checkbox */
  .checkbox-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 0;
    cursor: pointer;
  }
  .checkbox-row input[type="checkbox"] {
    width: 18px;
    height: 18px;
    margin-top: 1px;
    flex-shrink: 0;
    cursor: pointer;
    accent-color: var(--primary-color, #03a9f4);
  }
  .checkbox-row span { font-size: 13px; line-height: 1.4; }

  /* Token detail stat row */
  .stat-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .stat-item { display: flex; flex-direction: column; gap: 2px; }
  .stat-label { font-size: 11px; color: var(--secondary-text-color, #9e9e9e); text-transform: uppercase; letter-spacing: 0.06em; }
  .stat-value { font-size: 15px; font-weight: 500; }

  /* Reload button */
  .reload-btn {
    background: none;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 4px;
    cursor: pointer;
    padding: 4px 8px;
    font-size: 12px;
    color: var(--secondary-text-color, #9e9e9e);
    transition: background 0.15s;
  }
  .reload-btn:hover { background: var(--secondary-background-color, #f5f5f5); }

  /* Kill switch */
  .kill-switch-active {
    background: rgba(244,67,54,0.08);
    border: 2px solid var(--error-color, #f44336);
    border-radius: 8px;
    padding: 14px 16px;
  }

  /* Pagination */
  .pagination {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    justify-content: flex-end;
  }
  .pagination span { font-size: 13px; color: var(--secondary-text-color, #9e9e9e); }
`;

function Loading() {
  return (
    <div className="loading-wrap">
      <div className="spinner" />
      <span>Loading...</span>
    </div>
  );
}

function ErrorMsg({ msg }: { msg: string }) {
  return <div className="banner banner-error">{msg}</div>;
}

export { Loading, ErrorMsg };

type View =
  | { name: "list" }
  | { name: "detail"; tokenId: string };

function ATMApp({ hass, narrow }: { hass: unknown; narrow: boolean }) {
  const [tab, setTab] = useState<Tab>("tokens");
  const [view, setView] = useState<View>({ name: "list" });
  const [tokens, setTokens] = useState<TokenRecord[]>([]);
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [loadingTokens, setLoadingTokens] = useState(true);
  const [tokensError, setTokensError] = useState<string | null>(null);
  const [showArchivedTokens, setShowArchivedTokens] = useState(false);
  const menuRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (menuRef.current) {
      (menuRef.current as Record<string, unknown>).hass = hass;
      (menuRef.current as Record<string, unknown>).narrow = narrow;
    }
  }, [hass, narrow]);

  const refreshTokens = useCallback(async () => {
    setLoadingTokens(true);
    setTokensError(null);
    try {
      const data = await api.listTokens();
      setTokens(data);
    } catch (e: unknown) {
      setTokensError(e instanceof Error ? e.message : "Failed to load tokens.");
    } finally {
      setLoadingTokens(false);
    }
  }, []);

  useEffect(() => {
    refreshTokens();
    api.getSettings().then(setSettings).catch(() => null);
  }, [refreshTokens]);

  const openDetail = useCallback((id: string) => {
    setView({ name: "detail", tokenId: id });
    setTab("tokens");
  }, []);

  const goBack = useCallback(() => {
    setView({ name: "list" });
    refreshTokens();
  }, [refreshTokens]);

  return (
    <div className="atm-shell">
      {narrow && (
        <div className="atm-header">
          <ha-menu-button ref={menuRef as React.RefObject<HTMLElement>} />
          <span className="atm-header-title">ATM</span>
        </div>
      )}
      <div className="atm-tabs">
        {(["tokens", "audit", "settings"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`atm-tab${tab === t ? " active" : ""}`}
            onClick={() => {
              setTab(t);
              if (t !== "tokens") setView({ name: "list" });
              if (t === "tokens" || t === "audit") refreshTokens();
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="atm-content">
        {tab === "tokens" && view.name === "list" && (
          <TokenListView
            tokens={tokens}
            loading={loadingTokens}
            error={tokensError}
            onRefresh={refreshTokens}
            onOpenDetail={openDetail}
            showArchived={showArchivedTokens}
            onShowArchivedChange={setShowArchivedTokens}
          />
        )}
        {tab === "tokens" && view.name === "detail" && (
          <TokenDetailView
            tokenId={view.tokenId}
            onBack={goBack}
            onRefresh={refreshTokens}
          />
        )}
        {tab === "audit" && <AuditView tokens={tokens} />}
        {tab === "settings" && (
          <SettingsView
            settings={settings}
            onSettingsChange={setSettings}
          />
        )}
      </div>
    </div>
  );
}

class ATMPanelElement extends HTMLElement {
  private _root: Root | null = null;
  private _hass: unknown = null;
  private _narrow: boolean = false;
  private _prevUserId: string | undefined = undefined;

  connectedCallback() {
    this.style.touchAction = "pan-y";
    const shadow = this.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = PANEL_CSS;
    shadow.appendChild(style);

    const mount = document.createElement("div");
    mount.style.height = "100%";
    shadow.appendChild(mount);

    this._root = createRoot(mount);
    this._render();
  }

  disconnectedCallback() {
    this._root?.unmount();
    this._root = null;
  }

  set hass(hass: unknown) {
    this._hass = hass;
    setHass(hass); // update on every invocation so token is always current
    const uid = (hass as Record<string, Record<string, string>> | null)?.user?.id;
    if (uid !== this._prevUserId) {
      this._prevUserId = uid;
      this._render();
    }
  }

  set narrow(value: boolean) {
    if (this._narrow !== value) {
      this._narrow = value;
      this._render();
    }
  }

  private _render() {
    if (this._root) {
      this._root.render(<ATMApp hass={this._hass} narrow={this._narrow} />);
    }
  }
}

if (!customElements.get("atm-panel")) {
  customElements.define("atm-panel", ATMPanelElement);
}
