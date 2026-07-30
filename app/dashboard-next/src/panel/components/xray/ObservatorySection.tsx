import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_BURST_OBSERVATORY,
  DEFAULT_OBSERVATORY,
  fetchObservatory,
  saveObservatory,
} from "../../lib/observatoryApi";
import { useFetch } from "../../lib/useFetch";
import { Button, Callout, Card, EmptyState, Field, Input, MultiSelect, SkeletonRows, Toggle, useToast } from "../ui";
import { IcRefresh } from "../icons";
import { JsonCodeEditor } from "./JsonCodeEditor";

function parseJsonObject(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export const ObservatorySection: FC<{
  config: Record<string, unknown>;
  onChange: (c: Record<string, unknown>) => void;
}> = ({ config, onChange }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const remote = useFetch(fetchObservatory, []);
  const outboundTags = useMemo(() => {
    const outbounds = (config.outbounds || []) as Record<string, unknown>[];
    return outbounds.map((o) => String(o.tag || "")).filter(Boolean);
  }, [config.outbounds]);

  const [obsEnabled, setObsEnabled] = useState(false);
  const [burstEnabled, setBurstEnabled] = useState(false);
  const [obs, setObs] = useState<Record<string, unknown>>({ ...DEFAULT_OBSERVATORY });
  const [burst, setBurst] = useState<Record<string, unknown>>({ ...DEFAULT_BURST_OBSERVATORY });
  const [obsJson, setObsJson] = useState(prettyJson(DEFAULT_OBSERVATORY));
  const [burstJson, setBurstJson] = useState(prettyJson(DEFAULT_BURST_OBSERVATORY));
  const [obsAdvanced, setObsAdvanced] = useState(false);
  const [burstAdvanced, setBurstAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!remote.data) return;
    const classic = remote.data.observatory;
    const burstCfg = remote.data.burstObservatory;
    const nextObs = classic && typeof classic === "object" ? { ...classic } : { ...DEFAULT_OBSERVATORY };
    const nextBurst = burstCfg && typeof burstCfg === "object" ? { ...burstCfg } : { ...DEFAULT_BURST_OBSERVATORY };
    setObsEnabled(!!classic);
    setBurstEnabled(!!burstCfg);
    setObs(nextObs);
    setBurst(nextBurst);
    setObsJson(prettyJson(nextObs));
    setBurstJson(prettyJson(nextBurst));
  }, [remote.data]);

  const patchObs = (patch: Record<string, unknown>) => {
    setObs((prev) => {
      const next = { ...prev, ...patch };
      setObsJson(prettyJson(next));
      return next;
    });
  };

  const patchBurstPing = (patch: Record<string, unknown>) => {
    setBurst((prev) => {
      const ping = { ...((prev.pingConfig || {}) as Record<string, unknown>), ...patch };
      const next = { ...prev, pingConfig: ping };
      setBurstJson(prettyJson(next));
      return next;
    });
  };

  const patchBurstSelector = (selector: string[]) => {
    setBurst((prev) => {
      const next = { ...prev, subjectSelector: selector };
      setBurstJson(prettyJson(next));
      return next;
    });
  };

  const toggleObs = (enabled: boolean) => {
    setObsEnabled(enabled);
    if (enabled && !obs.subjectSelector) {
      patchObs({ ...DEFAULT_OBSERVATORY, subjectSelector: outboundTags.slice(0, 1) });
    }
  };

  const toggleBurst = (enabled: boolean) => {
    setBurstEnabled(enabled);
    if (enabled && !burst.subjectSelector) {
      const next = { ...DEFAULT_BURST_OBSERVATORY, subjectSelector: outboundTags.slice(0, 1) };
      setBurst(next);
      setBurstJson(prettyJson(next));
    }
  };

  const save = async () => {
    let classicPayload: Record<string, unknown> | null = null;
    let burstPayload: Record<string, unknown> | null = null;

    if (obsEnabled) {
      classicPayload = obsAdvanced ? parseJsonObject(obsJson) : { ...obs };
      if (!classicPayload) {
        toast.push(t("xray.observatoryInvalidJson"), "error");
        return;
      }
    }
    if (burstEnabled) {
      burstPayload = burstAdvanced ? parseJsonObject(burstJson) : { ...burst };
      if (!burstPayload) {
        toast.push(t("xray.burstObservatoryInvalidJson"), "error");
        return;
      }
    }

    setSaving(true);
    try {
      const saved = await saveObservatory({
        observatory: classicPayload,
        burstObservatory: burstPayload,
      });
      onChange(saved);
      toast.push(t("xray.savedRestart"), "success");
      remote.reload();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  };

  if (remote.loading && !remote.data) {
    return <Card><SkeletonRows rows={4} cols={2} /></Card>;
  }

  if (remote.error) {
    return (
      <EmptyState
        title={t("common.error")}
        desc={remote.error}
        action={<Button onClick={remote.reload}><IcRefresh className="sk-ico" /> {t("common.retry")}</Button>}
      />
    );
  }

  const obsPing = (burst.pingConfig || {}) as Record<string, unknown>;

  return (
    <div className="sk-stack">
      <Callout tone="info" title={t("xray.observatoryTitle")}>
        {t("xray.observatoryDesc")}
      </Callout>

      <Card>
        <div className="sk-row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>{t("xray.observatoryClassic")}</strong>
          <Toggle on={obsEnabled} onChange={toggleObs} label={obsEnabled ? t("common.enabled") : t("common.disabled")} />
        </div>
        {!obsEnabled ? (
          <EmptyState title={t("xray.observatoryDisabledTitle")} desc={t("xray.observatoryDisabledDesc")} />
        ) : obsAdvanced ? (
          <>
            <Field label={t("xray.observatoryJson")}>
              <JsonCodeEditor value={obsJson} onChange={setObsJson} minLines={12} />
            </Field>
            <Button size="sm" variant="ghost" onClick={() => setObsAdvanced(false)}>
              {t("xray.observatoryStructured")}
            </Button>
          </>
        ) : (
          <>
            <Field label={t("xray.observatorySubjectSelector")} hint={t("xray.observatorySubjectHint")}>
              <MultiSelect
                values={(obs.subjectSelector as string[]) || []}
                options={outboundTags}
                allowCustom
                onChange={(next) => patchObs({ subjectSelector: next })}
              />
            </Field>
            <Field label={t("xray.observatoryProbeUrl")}>
              <Input
                value={String(obs.probeUrl || "")}
                onChange={(e) => patchObs({ probeUrl: e.target.value })}
              />
            </Field>
            <Field label={t("xray.observatoryProbeInterval")}>
              <Input
                value={String(obs.probeInterval || "")}
                onChange={(e) => patchObs({ probeInterval: e.target.value })}
              />
            </Field>
            <Field label={t("xray.observatoryEnableConcurrency")}>
              <Toggle
                on={!!obs.enableConcurrency}
                onChange={(v) => patchObs({ enableConcurrency: v })}
                label={obs.enableConcurrency ? t("common.yes") : t("common.no")}
              />
            </Field>
            <Button size="sm" variant="ghost" onClick={() => setObsAdvanced(true)}>
              {t("xray.observatoryAdvancedJson")}
            </Button>
          </>
        )}
      </Card>

      <Card>
        <div className="sk-row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>{t("xray.burstObservatoryTitle")}</strong>
          <Toggle on={burstEnabled} onChange={toggleBurst} label={burstEnabled ? t("common.enabled") : t("common.disabled")} />
        </div>
        {!burstEnabled ? (
          <EmptyState title={t("xray.burstObservatoryDisabledTitle")} desc={t("xray.burstObservatoryDisabledDesc")} />
        ) : burstAdvanced ? (
          <>
            <Field label={t("xray.burstObservatoryJson")}>
              <JsonCodeEditor value={burstJson} onChange={setBurstJson} minLines={14} />
            </Field>
            <Button size="sm" variant="ghost" onClick={() => setBurstAdvanced(false)}>
              {t("xray.observatoryStructured")}
            </Button>
          </>
        ) : (
          <>
            <Field label={t("xray.observatorySubjectSelector")} hint={t("xray.burstObservatorySubjectHint")}>
              <MultiSelect
                values={(burst.subjectSelector as string[]) || []}
                options={outboundTags}
                allowCustom
                onChange={patchBurstSelector}
              />
            </Field>
            <Field label={t("xray.burstPingDestination")}>
              <Input
                value={String(obsPing.destination || "")}
                onChange={(e) => patchBurstPing({ destination: e.target.value })}
              />
            </Field>
            <Field label={t("xray.burstPingInterval")}>
              <Input
                value={String(obsPing.interval || "")}
                onChange={(e) => patchBurstPing({ interval: e.target.value })}
              />
            </Field>
            <Field label={t("xray.burstPingTimeout")}>
              <Input
                value={String(obsPing.timeout || "")}
                onChange={(e) => patchBurstPing({ timeout: e.target.value })}
              />
            </Field>
            <Field label={t("xray.burstPingConnectivity")}>
              <Input
                value={String(obsPing.connectivity || "")}
                onChange={(e) => patchBurstPing({ connectivity: e.target.value })}
                placeholder={t("xray.burstPingConnectivityPlaceholder")}
              />
            </Field>
            <Field label={t("xray.burstPingSamplingCount")}>
              <Input
                type="number"
                min={1}
                value={String(obsPing.samplingCount ?? 1)}
                onChange={(e) => patchBurstPing({ samplingCount: Number(e.target.value) || 1 })}
              />
            </Field>
            <Button size="sm" variant="ghost" onClick={() => setBurstAdvanced(true)}>
              {t("xray.observatoryAdvancedJson")}
            </Button>
          </>
        )}
      </Card>

      <div className="sk-row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <Button variant="ghost" disabled={remote.loading} onClick={remote.reload}>
          <IcRefresh className="sk-ico" /> {t("common.refresh")}
        </Button>
        <Button variant="primary" disabled={saving} onClick={() => void save()}>
          {saving ? t("common.loading") : t("common.save")}
        </Button>
      </div>
    </div>
  );
};
