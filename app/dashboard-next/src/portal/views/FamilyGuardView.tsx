"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, Plus, Shield, X } from "lucide-react";
import { portalGet, portalPut } from "@/lib/portal-api";
import { pt } from "@/lib/portal-i18n";
import { AccountPickerStrip, PageHeader } from "../components/Shell";
import { usePortal } from "../PortalContext";

type FamilyService = {
  id: string;
  label: string;
  category: string;
  popular: boolean;
  aliases?: string[];
  domain_count: number;
};

type FamilyPreset = {
  id: string;
  label: string;
  hint: string;
  block_adult: boolean;
  block_ads: boolean;
  services: string[];
};

type FamilyControls = {
  enabled: boolean;
  block_adult: boolean;
  block_ads: boolean;
  services: string[];
  custom_domains: string[];
  schedule: {
    tz: string;
    windows: Record<string, string[][]>;
    daily_minutes: number | null;
  };
  pause_until: number | null;
  pin_set: boolean;
  pause_active: boolean;
  runtime?: {
    day?: string | null;
    used_seconds?: number;
    schedule_blocked?: boolean;
    block_reason?: string | null;
  };
};

type FamilyResponse = {
  username: string;
  controls: FamilyControls;
  services: FamilyService[];
  presets: FamilyPreset[];
};

const DAY_KEYS = ["1", "2", "3", "4", "5", "6", "7"] as const;
const CAT_ORDER = ["social", "video", "chat", "game", "dating", "adult", "other"] as const;

const DAILY_OPTIONS: { value: string; labelKey: string }[] = [
  { value: "", labelKey: "familyDailyNone" },
  { value: "60", labelKey: "familyDaily1h" },
  { value: "120", labelKey: "familyDaily2h" },
  { value: "180", labelKey: "familyDaily3h" },
  { value: "240", labelKey: "familyDaily4h" },
];

function emptyWindows(): Record<string, string[][]> {
  return Object.fromEntries(DAY_KEYS.map((d) => [d, []])) as Record<string, string[][]>;
}

function windowsAllSame(windows: Record<string, string[][]>): { start: string; end: string } | null {
  const first = windows["1"] || [];
  if (first.length !== 1) return null;
  const [start, end] = first[0];
  for (const d of DAY_KEYS) {
    const w = windows[d] || [];
    if (w.length !== 1 || w[0][0] !== start || w[0][1] !== end) return null;
  }
  return { start, end };
}

export function FamilyGuardView() {
  const { lang, activeUsername, showToast, busy: globalBusy } = usePortal();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [catalog, setCatalog] = useState<FamilyService[]>([]);
  const [presets, setPresets] = useState<FamilyPreset[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [blockAdult, setBlockAdult] = useState(true);
  const [blockAds, setBlockAds] = useState(false);
  const [services, setServices] = useState<string[]>([]);
  const [customDomains, setCustomDomains] = useState<string[]>([]);
  const [domainInput, setDomainInput] = useState("");
  const [serviceQuery, setServiceQuery] = useState("");
  const [activeCat, setActiveCat] = useState<string>("all");
  const [dailyMinutes, setDailyMinutes] = useState("");
  const [scheduleOn, setScheduleOn] = useState(false);
  const [dayStart, setDayStart] = useState("16:00");
  const [dayEnd, setDayEnd] = useState("20:00");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pinSet, setPinSet] = useState(false);
  const [pin, setPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [pauseActive, setPauseActive] = useState(false);
  const [runtimeHint, setRuntimeHint] = useState("");

  const catLabel = useCallback(
    (cat: string) => {
      if (cat === "all") return pt(lang, "familyCat_all");
      const key = `familyCat_${cat}`;
      const t = pt(lang, key);
      return t === key ? cat : t;
    },
    [lang],
  );

  const byId = useMemo(() => {
    const m = new Map<string, FamilyService>();
    for (const s of catalog) m.set(s.id, s);
    return m;
  }, [catalog]);

  const load = useCallback(async () => {
    if (!activeUsername) return;
    setLoading(true);
    try {
      const data = await portalGet<FamilyResponse>(
        `/portal/accounts/${encodeURIComponent(activeUsername)}/family-controls`,
      );
      const c = data.controls;
      setCatalog(data.services || []);
      setPresets(data.presets || []);
      setEnabled(Boolean(c.enabled));
      setBlockAdult(Boolean(c.block_adult));
      setBlockAds(Boolean(c.block_ads));
      setServices([...(c.services || [])]);
      setCustomDomains([...(c.custom_domains || [])]);
      setDailyMinutes(
        c.schedule?.daily_minutes != null && c.schedule.daily_minutes > 0
          ? String(c.schedule.daily_minutes)
          : "",
      );
      const wins = { ...emptyWindows(), ...(c.schedule?.windows || {}) };
      const same = windowsAllSame(wins);
      const anyWin = Object.values(wins).some((w) => w.length > 0);
      if (same) {
        setScheduleOn(true);
        setDayStart(same.start);
        setDayEnd(same.end);
      } else if (anyWin) {
        setScheduleOn(true);
        setShowAdvanced(true);
        const first = Object.values(wins).find((w) => w.length)?.[0];
        if (first) {
          setDayStart(first[0]);
          setDayEnd(first[1]);
        }
      } else {
        setScheduleOn(false);
      }
      setPinSet(Boolean(c.pin_set));
      setPauseActive(Boolean(c.pause_active));
      const reason = c.runtime?.block_reason;
      if (c.runtime?.schedule_blocked && reason) {
        setRuntimeHint(
          reason === "daily_limit"
            ? pt(lang, "familyBlockedDaily")
            : pt(lang, "familyBlockedSchedule"),
        );
      } else if (c.pause_active) {
        setRuntimeHint(pt(lang, "familyPausedHint"));
      } else {
        setRuntimeHint("");
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setLoading(false);
    }
  }, [activeUsername, lang, showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const buildWindows = (): Record<string, string[][]> => {
    if (!scheduleOn) return emptyWindows();
    const slot: string[][] = [[dayStart, dayEnd]];
    return Object.fromEntries(DAY_KEYS.map((d) => [d, slot])) as Record<string, string[][]>;
  };

  const available = useMemo(() => {
    const q = serviceQuery.trim().toLowerCase();
    const selected = new Set(services);
    return catalog.filter((s) => {
      if (selected.has(s.id)) return false;
      if (activeCat !== "all" && s.category !== activeCat) return false;
      if (!q) return true;
      if (s.label.toLowerCase().includes(q) || s.id.toLowerCase().includes(q)) return true;
      return (s.aliases || []).some((a) => a.toLowerCase().includes(q));
    });
  }, [catalog, services, serviceQuery, activeCat]);

  const selectedItems = useMemo(
    () => services.map((id) => byId.get(id) || { id, label: id, category: "other", popular: false, domain_count: 0 }),
    [services, byId],
  );

  const addService = (id: string) => {
    setServices((prev) => (prev.includes(id) ? prev : [...prev, id]));
  };

  const removeService = (id: string) => {
    setServices((prev) => prev.filter((x) => x !== id));
  };

  const addAllVisible = () => {
    const ids = available.map((s) => s.id);
    if (!ids.length) return;
    setServices((prev) => {
      const set = new Set(prev);
      for (const id of ids) set.add(id);
      return Array.from(set);
    });
  };

  const clearSelected = () => setServices([]);

  const applyPreset = (p: FamilyPreset) => {
    setEnabled(true);
    setBlockAdult(p.block_adult);
    setBlockAds(p.block_ads);
    setServices([...p.services]);
    showToast(pt(lang, "familyPresetApplied").replace("{name}", p.label));
  };

  const addDomain = () => {
    const raw = domainInput.trim().toLowerCase();
    if (!raw) return;
    const cleaned = raw
      .replace(/^https?:\/\//, "")
      .split("/")[0]
      .replace(/^\*\./, "")
      .replace(/^www\./, "");
    if (!cleaned.includes(".")) {
      showToast(pt(lang, "familyDomainInvalid"));
      return;
    }
    if (!customDomains.includes(cleaned)) {
      setCustomDomains((d) => [...d, cleaned]);
    }
    setDomainInput("");
  };

  const save = async (extra?: { pause_minutes?: number; clear_pin?: boolean }) => {
    if (!activeUsername) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        enabled,
        block_adult: blockAdult,
        block_ads: blockAds,
        services,
        custom_domains: customDomains,
        schedule: {
          tz: "Asia/Tehran",
          windows: buildWindows(),
          daily_minutes: dailyMinutes.trim() ? parseInt(dailyMinutes, 10) : null,
        },
      };
      if (pin.trim()) body.pin = pin.trim();
      if (newPin.trim()) body.new_pin = newPin.trim();
      if (extra?.pause_minutes) body.pause_minutes = extra.pause_minutes;
      if (extra?.clear_pin) body.clear_pin = true;

      await portalPut(
        `/portal/accounts/${encodeURIComponent(activeUsername)}/family-controls`,
        body,
      );
      setPin("");
      setNewPin("");
      showToast(pt(lang, "familySaved"));
      await load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : pt(lang, "error"));
    } finally {
      setSaving(false);
    }
  };

  const disabled = loading || saving || globalBusy || !activeUsername;
  const cats = useMemo(() => {
    const present = new Set(catalog.map((s) => s.category));
    return ["all", ...CAT_ORDER.filter((c) => present.has(c))];
  }, [catalog]);

  return (
    <div className="p-stack">
      <PageHeader title={pt(lang, "familyTitle")} hint={pt(lang, "familyHintSimple")} />
      <AccountPickerStrip title={pt(lang, "familyPickAccount")} />

      {runtimeHint ? (
        <div className="p-card p-card-pad p-family-banner" role="status">
          {runtimeHint}
        </div>
      ) : null}

      <section className="p-card p-card-pad p-family">
        <div className="p-family-row">
          <div>
            <h2 className="p-section-title" style={{ margin: 0 }}>
              {pt(lang, "familyEnable")}
            </h2>
            <p className="p-muted" style={{ margin: "0.35rem 0 0" }}>
              {pt(lang, "familyEnableHint")}
            </p>
          </div>
          <label className="p-family-switch">
            <input
              type="checkbox"
              checked={enabled}
              disabled={disabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span />
          </label>
        </div>

        <div className="p-family-row">
          <div>
            <strong>{pt(lang, "familyAdult")}</strong>
            <p className="p-muted" style={{ margin: "0.2rem 0 0" }}>
              {pt(lang, "familyAdultHint")}
            </p>
          </div>
          <label className="p-family-switch">
            <input
              type="checkbox"
              checked={blockAdult}
              disabled={disabled}
              onChange={(e) => setBlockAdult(e.target.checked)}
            />
            <span />
          </label>
        </div>

        <div className="p-family-row">
          <div>
            <strong>{pt(lang, "familyAds")}</strong>
          </div>
          <label className="p-family-switch">
            <input
              type="checkbox"
              checked={blockAds}
              disabled={disabled}
              onChange={(e) => setBlockAds(e.target.checked)}
            />
            <span />
          </label>
        </div>
      </section>

      {presets.length ? (
        <section className="p-card p-card-pad">
          <h2 className="p-section-title">{pt(lang, "familyQuick")}</h2>
          <p className="p-muted">{pt(lang, "familyQuickHint")}</p>
          <div className="p-family-presets">
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                className="p-family-preset"
                disabled={disabled}
                onClick={() => applyPreset(p)}
              >
                <strong>{p.label}</strong>
                <span>{p.hint}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="p-card p-card-pad">
        <h2 className="p-section-title">{pt(lang, "familyBlockedList")}</h2>
        <p className="p-muted">{pt(lang, "familyBlockedListHint")}</p>
        <div className="p-family-blocked">
          {selectedItems.length === 0 ? (
            <p className="p-muted">{pt(lang, "familyBlockedEmpty")}</p>
          ) : (
            selectedItems.map((s) => (
              <button
                key={s.id}
                type="button"
                className="p-family-blocked-item"
                disabled={disabled}
                onClick={() => removeService(s.id)}
                title={pt(lang, "familyRemoveApp")}
              >
                <span>{s.label}</span>
                <X size={14} aria-hidden />
              </button>
            ))
          )}
        </div>
        {selectedItems.length ? (
          <button
            type="button"
            className="p-btn ghost"
            style={{ marginTop: "0.65rem" }}
            disabled={disabled}
            onClick={clearSelected}
          >
            {pt(lang, "familyClearBlocked")}
          </button>
        ) : null}
      </section>

      <section className="p-card p-card-pad">
        <h2 className="p-section-title">{pt(lang, "familyPickApps")}</h2>
        <p className="p-muted">{pt(lang, "familyPickAppsHint")}</p>
        <div className="p-field">
          <input
            className="p-input"
            value={serviceQuery}
            onChange={(e) => setServiceQuery(e.target.value)}
            placeholder={pt(lang, "familySearchApp")}
            disabled={disabled}
          />
        </div>
        <div className="p-family-cats" role="tablist">
          {cats.map((c) => (
            <button
              key={c}
              type="button"
              role="tab"
              aria-selected={activeCat === c}
              className={`p-family-cat-chip${activeCat === c ? " is-on" : ""}`}
              disabled={disabled}
              onClick={() => setActiveCat(c)}
            >
              {catLabel(c)}
            </button>
          ))}
        </div>
        <div className="p-family-pick-actions">
          <button type="button" className="p-btn ghost" disabled={disabled || !available.length} onClick={addAllVisible}>
            {pt(lang, "familyAddAllVisible")}
          </button>
        </div>
        <div className="p-family-catalog">
          {available.length === 0 ? (
            <p className="p-muted">{pt(lang, "familyCatalogEmpty")}</p>
          ) : (
            available.map((s) => (
              <button
                key={s.id}
                type="button"
                className="p-family-catalog-item"
                disabled={disabled}
                onClick={() => addService(s.id)}
              >
                <span>
                  <strong>{s.label}</strong>
                  <em>{catLabel(s.category)}</em>
                </span>
                <Plus size={16} aria-hidden />
              </button>
            ))
          )}
        </div>
      </section>

      <section className="p-card p-card-pad">
        <h2 className="p-section-title">{pt(lang, "familyTimeSimple")}</h2>
        <p className="p-muted">{pt(lang, "familyTimeSimpleHint")}</p>

        <div className="p-family-row">
          <div>
            <strong>{pt(lang, "familyLimitHours")}</strong>
            <p className="p-muted" style={{ margin: "0.2rem 0 0" }}>
              {pt(lang, "familyLimitHoursHint")}
            </p>
          </div>
          <label className="p-family-switch">
            <input
              type="checkbox"
              checked={scheduleOn}
              disabled={disabled}
              onChange={(e) => setScheduleOn(e.target.checked)}
            />
            <span />
          </label>
        </div>

        {scheduleOn ? (
          <div className="p-family-time-row">
            <label>
              {pt(lang, "familyFrom")}
              <input
                className="p-input"
                type="time"
                value={dayStart}
                disabled={disabled}
                onChange={(e) => setDayStart(e.target.value)}
              />
            </label>
            <label>
              {pt(lang, "familyTo")}
              <input
                className="p-input"
                type="time"
                value={dayEnd}
                disabled={disabled}
                onChange={(e) => setDayEnd(e.target.value)}
              />
            </label>
          </div>
        ) : null}

        <div className="p-family-daily" style={{ marginTop: "1rem" }}>
          <div className="p-family-daily-label">{pt(lang, "familyDailyMinutes")}</div>
          <p className="p-muted" style={{ margin: "0.25rem 0 0.65rem" }}>
            {pt(lang, "familyDailyHint")}
          </p>
          <div className="p-family-daily-chips" role="radiogroup" aria-label={pt(lang, "familyDailyMinutes")}>
            {DAILY_OPTIONS.map((opt) => {
              const on = dailyMinutes === opt.value;
              return (
                <button
                  key={opt.value || "none"}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className={`p-family-daily-chip${on ? " is-on" : ""}`}
                  disabled={disabled}
                  onClick={() => setDailyMinutes(opt.value)}
                >
                  {pt(lang, opt.labelKey)}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      <section className="p-card p-card-pad">
        <button
          type="button"
          className="p-family-adv-toggle"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          <span>{pt(lang, "familyAdvanced")}</span>
          <ChevronDown
            size={18}
            style={{ transform: showAdvanced ? "rotate(180deg)" : undefined, transition: "0.15s" }}
          />
        </button>

        {showAdvanced ? (
          <div className="p-family-advanced">
            <h3 className="p-section-title">{pt(lang, "familyCustom")}</h3>
            <p className="p-muted">{pt(lang, "familyCustomHintSimple")}</p>
            <div className="p-family-domain-add">
              <input
                className="p-input"
                value={domainInput}
                onChange={(e) => setDomainInput(e.target.value)}
                placeholder={pt(lang, "familyDomainPh")}
                dir="ltr"
                disabled={disabled}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addDomain();
                  }
                }}
              />
              <button type="button" className="p-btn" disabled={disabled} onClick={addDomain}>
                {pt(lang, "familyAddDomain")}
              </button>
            </div>
            <div className="p-family-domains">
              {customDomains.map((d) => (
                <button
                  key={d}
                  type="button"
                  className="p-chip"
                  disabled={disabled}
                  onClick={() => setCustomDomains((xs) => xs.filter((x) => x !== d))}
                >
                  <span dir="ltr">{d}</span> ×
                </button>
              ))}
            </div>

            <h3 className="p-section-title" style={{ marginTop: "1.25rem" }}>
              {pt(lang, "familyPin")}
            </h3>
            <p className="p-muted">{pt(lang, "familyPinHint")}</p>
            {pinSet ? (
              <div className="p-field">
                <label htmlFor="family-pin">{pt(lang, "familyCurrentPin")}</label>
                <input
                  id="family-pin"
                  className="p-input"
                  type="password"
                  inputMode="numeric"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  disabled={disabled}
                  autoComplete="off"
                />
              </div>
            ) : null}
            <div className="p-field">
              <label htmlFor="family-new-pin">
                {pinSet ? pt(lang, "familyNewPin") : pt(lang, "familySetPin")}
              </label>
              <input
                id="family-new-pin"
                className="p-input"
                type="password"
                inputMode="numeric"
                value={newPin}
                onChange={(e) => setNewPin(e.target.value)}
                disabled={disabled}
                placeholder="1234"
                autoComplete="off"
              />
            </div>
            {pinSet ? (
              <button
                type="button"
                className="p-btn ghost"
                disabled={disabled}
                onClick={() => void save({ clear_pin: true })}
              >
                {pt(lang, "familyClearPin")}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      <div className="p-family-actions">
        <button
          type="button"
          className="p-btn primary"
          disabled={disabled}
          onClick={() => void save()}
        >
          <Shield size={16} aria-hidden />
          {saving ? pt(lang, "loading") : pt(lang, "familySave")}
        </button>
        <button
          type="button"
          className="p-btn"
          disabled={disabled || !enabled}
          onClick={() => void save({ pause_minutes: 60 })}
        >
          {pauseActive ? pt(lang, "familyPausedHint") : pt(lang, "familyPause1h")}
        </button>
      </div>
    </div>
  );
}
