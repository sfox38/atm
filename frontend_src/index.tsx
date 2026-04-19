import React, { useState, useEffect, useCallback, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { TokenRecord, GlobalSettings } from "./types";
import { TokenListView } from "./views/TokenList";
import { TokenDetailView } from "./views/TokenDetail";
import { AuditView } from "./views/AuditView";
import { SettingsView } from "./views/SettingsView";
import { api, setHass } from "./api";
import PANEL_CSS from "./atm-panel.css?inline";

type Tab = "tokens" | "audit" | "settings";

const HIGH_RISK_DOMAINS = new Set([
  "homeassistant", "recorder", "system_log", "hassio",
  "backup", "notify", "persistent_notification", "mqtt",
]);

export { HIGH_RISK_DOMAINS };

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
