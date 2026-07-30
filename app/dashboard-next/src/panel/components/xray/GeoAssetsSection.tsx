import { FC, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { Button, Callout, Card, EmptyState, Field, useToast } from "../ui";
import { IcDownload, IcRefresh, IcTrash } from "../icons";
import { TableRowMenu } from "../TableRowMenu";

type GeoAsset = {
  name: string;
  size: number;
  modified_at: number;
  sha256: string;
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export const GeoAssetsSection: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [assetsPath, setAssetsPath] = useState("");
  const [assets, setAssets] = useState<GeoAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<{ path: string; assets: GeoAsset[] }>("/core/assets");
      setAssetsPath(res.path);
      setAssets(res.assets || []);
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => {
    reload();
  }, [reload]);

  const upload = async (file: File) => {
    if (!file.name.endsWith(".dat")) {
      toast.push(t("xray.geoInvalidName"), "error");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.upload("/core/assets/upload", fd);
      toast.push(t("xray.geoUploaded"), "success");
      reload();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const updateFromSource = async () => {
    setBusy(true);
    try {
      const res = await api.post<{ results: { name: string; ok: boolean; error?: string }[] }>(
        "/core/assets/update",
        {},
      );
      const failed = (res.results || []).filter((r) => !r.ok);
      if (failed.length) {
        toast.push(failed.map((f) => `${f.name}: ${f.error || "failed"}`).join("; "), "error");
      } else {
        toast.push(t("xray.geoUpdated"), "success");
      }
      reload();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (name: string) => {
    if (!confirm(t("common.confirmDelete"))) return;
    setBusy(true);
    try {
      await api.del(`/core/assets/${encodeURIComponent(name)}`);
      toast.push(t("common.deleted"), "success");
      reload();
    } catch (e: unknown) {
      toast.push(e instanceof Error ? e.message : t("common.error"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sk-stack">
      <Callout tone="info">{t("xray.geoAssetsDesc")}</Callout>
      {assetsPath && (
        <p className="sk-mono" style={{ fontSize: 12, opacity: 0.75 }}>
          {assetsPath}
        </p>
      )}
      <div className="sk-row" style={{ gap: 8, flexWrap: "wrap" }}>
        <Button variant="primary" disabled={busy} onClick={updateFromSource}>
          <IcRefresh className="sk-ico" /> {t("xray.geoUpdateDefault")}
        </Button>
        <Button disabled={busy} onClick={() => fileRef.current?.click()}>
          <IcDownload className="sk-ico" /> {t("xray.geoUpload")}
        </Button>
        <Button variant="ghost" disabled={busy || loading} onClick={reload}>
          <IcRefresh className="sk-ico" /> {t("common.refresh")}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".dat"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
            e.target.value = "";
          }}
        />
      </div>
      <Card pad0>
        {loading ? (
          <div className="sk-pad">{t("common.loading")}</div>
        ) : !assets.length ? (
          <EmptyState title={t("common.noData")} desc={t("xray.geoEmpty")} />
        ) : (
          <div className="sk-table-wrap">
            <table className="sk-table">
              <thead>
                <tr>
                  <th>{t("common.name")}</th>
                  <th>{t("xray.geoSize")}</th>
                  <th>{t("xray.geoModified")}</th>
                  <th>SHA256</th>
                  <th className="sk-actions">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => (
                  <tr key={a.name}>
                    <td><span className="sk-proto-name-main sk-mono">{a.name}</span></td>
                    <td className="sk-num">{formatBytes(a.size)}</td>
                    <td className="sk-proto-meta">{new Date(a.modified_at * 1000).toLocaleString()}</td>
                    <td className="sk-mono sk-proto-meta">{a.sha256.slice(0, 16)}…</td>
                    <td className="sk-actions">
                      <TableRowMenu
                        items={[
                          {
                            id: "del",
                            label: t("common.delete"),
                            icon: <IcTrash className="sk-ico" />,
                            danger: true,
                            disabled: busy,
                            onClick: () => remove(a.name),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
