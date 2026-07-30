import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import {
  Button, Callout, Card, CardHead, Field, Input, SkeletonRows, Tabs, useToast,
} from "../components/ui";

type SourceMode = "api" | "backup";

type PanelRow = {
  slug: string;
  base_url: string;
  username: string;
  password: string;
  backup_path: string;
  legacy_panel_id: string;
};

type MigrationResult = {
  panel_slug: string;
  applied: boolean;
  user_count: number;
  alias_count: number;
  users_created: number;
  users_updated: number;
  aliases_created: number;
  inbound_tags: string[];
  warnings: string[];
  error?: string | null;
  endpoint: Record<string, unknown>;
};

type UuidCollisions = {
  has_conflicts: boolean;
  collisions: Array<{
    type: string;
    uuid: string;
    first_panel: string;
    second_panel: string;
  }>;
};

const emptyPanel = (): PanelRow => ({
  slug: "",
  base_url: "",
  username: "",
  password: "",
  backup_path: "",
  legacy_panel_id: "",
});

const slugFromFilename = (name: string): string => {
  const base = name.replace(/\.(dump|sql|db|sqlite|sqlite3|json)$/i, "");
  const short = base.split(".")[0]?.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || base;
  return (short || base)
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .toLowerCase();
};

export const MigrationWizard: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [mode, setMode] = useState<SourceMode>("backup");
  const [panels, setPanels] = useState<PanelRow[]>([emptyPanel()]);
  const [results, setResults] = useState<MigrationResult[] | null>(null);
  const [uuidCollisions, setUuidCollisions] = useState<UuidCollisions | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ processed: number; total: number } | null>(null);
  const [uploadingIdx, setUploadingIdx] = useState<number | null>(null);

  const switchMode = (next: SourceMode) => {
    setMode(next);
    setResults(null);
    setUuidCollisions(null);
    setPanels([emptyPanel()]);
  };

  const update = (idx: number, patch: Partial<PanelRow>) => {
    setPanels((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const uploadBackup = async (idx: number, file: File | null) => {
    if (!file) return;
    setUploadingIdx(idx);
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await api.upload<{ path: string; filename: string }>("/migration/3x-ui/upload", form);
      const suggested = slugFromFilename(data.filename);
      const row = panels[idx];
      update(idx, {
        backup_path: data.path,
        slug: row.slug.trim() || suggested,
      });
      toast.push(t("migration.uploadDone", { name: data.filename }), "success");
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setUploadingIdx(null);
    }
  };

  const validate = (selected: PanelRow[]): boolean => {
    if (!selected.length) {
      toast.push(t("migration.needPanel"), "error");
      return false;
    }
    for (const p of selected) {
      if (mode === "api") {
        if (!p.base_url.trim()) {
          toast.push(t("migration.needApiUrl", { slug: p.slug || "?" }), "error");
          return false;
        }
        if (!p.username.trim() || !p.password.trim()) {
          toast.push(t("migration.needApiCredentials", { slug: p.slug || "?" }), "error");
          return false;
        }
      } else if (!p.backup_path.trim()) {
        toast.push(t("migration.needBackup", { slug: p.slug || "?" }), "error");
        return false;
      }
    }
    return true;
  };

  const pollJob = async (
    jobId: string,
  ): Promise<{ results: MigrationResult[]; uuid_collisions?: UuidCollisions }> => {
    // Poll the background import until it finishes, streaming progress.
    for (;;) {
      const s = await api.get<{
        state: string;
        processed: number;
        total: number;
        results: MigrationResult[];
        uuid_collisions?: UuidCollisions | null;
        error?: string | null;
      }>(`/migration/3x-ui/status/${jobId}`);
      setProgress({ processed: s.processed || 0, total: s.total || 0 });
      if (s.state === "done") {
        return { results: s.results || [], uuid_collisions: s.uuid_collisions ?? undefined };
      }
      if (s.state === "error") {
        throw new Error(s.error || t("common.error"));
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };

  const run = async (dryRun: boolean) => {
    const selected = panels.filter((p) => p.slug.trim());
    if (!validate(selected)) return;

    const payload = {
      dry_run: dryRun,
      panels: selected.map((p) => ({
        slug: p.slug.trim(),
        legacy_panel_id: p.legacy_panel_id.trim(),
        ...(mode === "api"
          ? {
              base_url: p.base_url.trim(),
              username: p.username.trim(),
              password: p.password,
              backup_path: "",
            }
          : {
              base_url: "",
              username: "",
              password: "",
              backup_path: p.backup_path.trim(),
            }),
      })),
    };

    setBusy(true);
    setProgress(null);
    try {
      let data: { results: MigrationResult[]; uuid_collisions?: UuidCollisions };
      if (dryRun) {
        data = await api.post<{ results: MigrationResult[]; uuid_collisions?: UuidCollisions }>(
          "/migration/3x-ui/dry-run",
          payload,
        );
      } else {
        // Real imports run in the background so the request returns instantly
        // (thousands of clients can outlive proxy/client timeouts). Poll status.
        const started = await api.post<{
          job_id?: string;
          async?: boolean;
          results?: MigrationResult[];
          uuid_collisions?: UuidCollisions;
        }>("/migration/3x-ui/run", payload);
        if (started.job_id) {
          setProgress({ processed: 0, total: 0 });
          data = await pollJob(started.job_id);
        } else {
          data = { results: started.results ?? [], uuid_collisions: started.uuid_collisions };
        }
      }
      setResults(data.results);
      setUuidCollisions(data.uuid_collisions ?? null);
      const failed = data.results.filter((r) => r.error);
      const ran = !dryRun && data.results.some((r) => r.applied);
      if (failed.length) {
        toast.push(failed[0].error || t("common.error"), "error");
      } else if (dryRun) {
        toast.push(t("migration.previewDone"), "success");
      } else if (data.results.every((r) => !r.applied || (r.users_created === 0 && r.users_updated === 0))) {
        toast.push(t("migration.runNoChanges"), "error");
      } else {
        toast.push(t("migration.runDone"), "success");
      }
      if (ran) {
        const totalCreated = data.results.reduce((n, r) => n + (r.users_created || 0), 0);
        const totalUpdated = data.results.reduce((n, r) => n + (r.users_updated || 0), 0);
        if (totalCreated + totalUpdated > 0) {
          toast.push(t("migration.runStats", { created: totalCreated, updated: totalUpdated }), "info");
        }
      }
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  const modeTabs = [
    { id: "backup", label: t("migration.modeBackup") },
    { id: "api", label: t("migration.modeApi") },
  ];

  return (
    <div className="sk-stack" style={{ gap: 16 }}>
      <Callout tone="info" title={t("migration.title")}>
        {mode === "backup" ? t("migration.descriptionBackup") : t("migration.descriptionApi")}
      </Callout>

      <Tabs tabs={modeTabs} active={mode} onChange={(id) => switchMode(id as SourceMode)} />

      {panels.map((p, idx) => (
        <Card key={idx}>
          <CardHead
            title={t("migration.panelN", { n: idx + 1 })}
            actions={
              panels.length > 1 ? (
                <Button variant="ghost" size="sm" onClick={() => setPanels((r) => r.filter((_, i) => i !== idx))}>
                  {t("common.remove")}
                </Button>
              ) : null
            }
          />
          <div className="sk-form-grid">
            <Field label={t("migration.slug")} hint={t("migration.slugHint")}>
              <Input
                value={p.slug}
                onChange={(e: any) => update(idx, { slug: e.target.value })}
                placeholder={mode === "backup" ? "p4" : "panel-de-vpn"}
              />
            </Field>

            {mode === "api" ? (
              <>
                <Field label={t("migration.baseUrl")}>
                  <Input
                    value={p.base_url}
                    onChange={(e: any) => update(idx, { base_url: e.target.value })}
                    placeholder="https://panel.example:2053"
                  />
                </Field>
                <Field label={t("migration.username")}>
                  <Input value={p.username} onChange={(e: any) => update(idx, { username: e.target.value })} />
                </Field>
                <Field label={t("migration.password")}>
                  <Input
                    type="password"
                    value={p.password}
                    onChange={(e: any) => update(idx, { password: e.target.value })}
                  />
                </Field>
              </>
            ) : (
              <>
                <Field label={t("migration.backupUpload")} hint={t("migration.backupUploadHint")}>
                  <input
                    type="file"
                    accept=".dump,.sql,.db,.sqlite,.sqlite3,.json"
                    disabled={uploadingIdx === idx || busy}
                    onChange={(e) => {
                      const f = e.target.files?.[0] || null;
                      void uploadBackup(idx, f);
                      e.target.value = "";
                    }}
                  />
                </Field>
                {p.backup_path ? (
                  <Field label={t("migration.backupPath")}>
                    <Input value={p.backup_path} readOnly />
                  </Field>
                ) : null}
                <p className="sk-faint" style={{ fontSize: 12, margin: 0 }}>
                  {t("migration.uploadOnlyHint")}
                </p>
              </>
            )}
          </div>
        </Card>
      ))}

      <div className="sk-share-row">
        <Button variant="ghost" onClick={() => setPanels((r) => [...r, emptyPanel()])}>{t("migration.addPanel")}</Button>
        <Button disabled={busy} onClick={() => run(true)}>{t("migration.dryRun")}</Button>
        <Button variant="primary" disabled={busy} onClick={() => run(false)}>{t("migration.run")}</Button>
      </div>

      {busy && progress ? (
        <Callout tone="info" title={t("migration.importing")}>
          {progress.total > 0
            ? t("migration.importProgress", { processed: progress.processed, total: progress.total })
            : t("migration.importStarting")}
          <div
            style={{
              marginTop: 8,
              height: 6,
              borderRadius: 4,
              background: "var(--sk-border, rgba(255,255,255,0.12))",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${progress.total > 0 ? Math.min(100, Math.round((progress.processed / progress.total) * 100)) : 8}%`,
                background: "var(--sk-accent, #2ee0c4)",
                transition: "width .4s ease",
              }}
            />
          </div>
        </Callout>
      ) : busy ? (
        <SkeletonRows rows={3} cols={3} />
      ) : null}

      {uuidCollisions?.has_conflicts ? (
        <Callout tone="warn" title={t("migration.uuidCollisionsTitle")}>
          <ul style={{ margin: "8px 0 0", paddingInlineStart: 18 }}>
            {uuidCollisions.collisions.map((c, i) => (
              <li key={i}>
                {t("migration.uuidCollisionLine", {
                  uuid: c.uuid,
                  first: c.first_panel,
                  second: c.second_panel,
                })}
              </li>
            ))}
          </ul>
        </Callout>
      ) : null}

      {results && (
        <Card>
          <CardHead title={t("migration.results")} />
          <div className="sk-stack" style={{ gap: 12 }}>
            {results.map((r) => (
              <div key={r.panel_slug} className="sk-faint" style={{ fontSize: 13 }}>
                <strong>{r.panel_slug}</strong>
                {r.error ? (
                  <div style={{ marginTop: 8 }}>
                    <Callout tone="warn" title={t("common.error")}>
                      {r.error}
                    </Callout>
                  </div>
                ) : (
                  <>
                    {" — "}
                    {r.applied ? t("migration.applied") : t("migration.previewOnly")}
                    {" · "}
                    {t("migration.summary", {
                      users: r.user_count,
                      aliases: r.alias_count,
                      created: r.users_created,
                      updated: r.users_updated,
                    })}
                  </>
                )}
                {r.warnings?.length ? (
                  <ul style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>
                    {r.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
};
