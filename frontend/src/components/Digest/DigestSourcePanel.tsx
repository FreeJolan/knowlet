import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Power, Rss, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createDigestSource,
  deleteDigestSource,
  listDigestSources,
  updateDigestSource,
  type DigestSourcePayload,
  type DigestSourceSummary,
} from "@/api/client";

export function DigestSourcePanel(): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [kind, setKind] = useState<"rss" | "prompt">("rss");
  const [name, setName] = useState("");
  const [rssUrl, setRssUrl] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);

  const sources = useQuery({
    queryKey: ["digest-sources"],
    queryFn: listDigestSources,
    staleTime: 10_000,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["digest-sources"] });
    void qc.invalidateQueries({ queryKey: ["digest-status"] });
  };

  const resetForm = () => {
    setName("");
    setRssUrl("");
    setPrompt("");
    setError(null);
  };

  const createMut = useMutation({
    mutationFn: createDigestSource,
    onSuccess: () => {
      resetForm();
      invalidate();
    },
    onError: (err) => setError(apiErrorMessage(err, t("settings.digest.saveFailed"))),
  });

  const updateMut = useMutation({
    mutationFn: (args: { id: string; payload: DigestSourcePayload }) =>
      updateDigestSource(args.id, args.payload),
    onSuccess: invalidate,
    onError: (err) => setError(apiErrorMessage(err, t("settings.digest.saveFailed"))),
  });

  const deleteMut = useMutation({
    mutationFn: deleteDigestSource,
    onSuccess: invalidate,
    onError: (err) => setError(apiErrorMessage(err, t("settings.digest.deleteFailed"))),
  });

  const submit = () => {
    setError(null);
    const payload: DigestSourcePayload =
      kind === "rss"
        ? {
            name: name.trim(),
            kind: "rss",
            url: rssUrl.trim(),
            enabled: true,
          }
        : {
            name: name.trim(),
            kind: "prompt",
            prompt: prompt.trim(),
            enabled: true,
          };
    createMut.mutate(payload);
  };

  const busy = createMut.isPending || updateMut.isPending || deleteMut.isPending;

  return (
    <section
      className="w-full space-y-4 rounded-md"
      style={{ background: "var(--bg)" }}
      data-testid="digest-source-panel"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-serif text-lg font-medium">
            {t("settings.digest.title")}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("digest.sourceConfigHint")}
          </p>
        </div>
      </div>

      <div
        className="rounded-md border p-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <SourceKindButton
            active={kind === "rss"}
            icon={<Rss className="size-3.5" />}
            label={t("settings.digest.kindRss")}
            onClick={() => {
              setKind("rss");
              setError(null);
            }}
            testId="digest-source-kind-rss"
          />
          <SourceKindButton
            active={kind === "prompt"}
            icon={<Sparkles className="size-3.5" />}
            label={t("settings.digest.kindPrompt")}
            onClick={() => {
              setKind("prompt");
              setError(null);
            }}
            testId="digest-source-kind-prompt"
          />
        </div>

        <div className="grid gap-2 md:grid-cols-[minmax(180px,0.45fr)_minmax(260px,1fr)]">
          <label className="grid gap-1 text-xs">
            <span className="text-muted-foreground">
              {t("settings.digest.nameLabel")}
            </span>
            <input
              data-testid="digest-source-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
              style={{ borderColor: "var(--line)" }}
            />
          </label>

          {kind === "rss" ? (
            <label className="grid gap-1 text-xs">
              <span className="text-muted-foreground">
                {t("settings.digest.rssUrlLabel")}
              </span>
              <input
                data-testid="digest-source-rss-url"
                value={rssUrl}
                onChange={(e) => setRssUrl(e.target.value)}
                className="rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
                style={{ borderColor: "var(--line)" }}
                placeholder="https://example.com/feed.xml"
              />
            </label>
          ) : (
            <label className="grid gap-1 text-xs">
              <span className="text-muted-foreground">
                {t("settings.digest.promptLabel")}
              </span>
              <textarea
                data-testid="digest-source-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={2}
                className="resize-none rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
                style={{ borderColor: "var(--line)" }}
              />
            </label>
          )}
        </div>

        {error && (
          <div
            className="mt-2 text-xs"
            style={{ color: "var(--danger, #c0392b)" }}
            data-testid="digest-source-error"
          >
            {error}
          </div>
        )}

        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            data-testid="digest-source-add"
            className="inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs disabled:opacity-50"
            style={{
              borderColor: "var(--accent)",
              background: "var(--accent-tint-2)",
            }}
          >
            <Plus className="size-3.5" />
            {createMut.isPending
              ? t("settings.digest.saving")
              : t("settings.digest.add")}
          </button>
        </div>
      </div>

      <div
        className="rounded-md border"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        {!sources.data && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.advanced.loading")}
          </div>
        )}
        {sources.data && sources.data.length === 0 && (
          <div className="p-3 text-[11px] text-muted-foreground">
            {t("settings.digest.empty")}
          </div>
        )}
        {sources.data?.map((source) => (
          <DigestSourceRow
            key={source.id}
            source={source}
            busy={busy}
            onToggle={() =>
              updateMut.mutate({
                id: source.id,
                payload: sourcePayloadFromSummary(source, !source.enabled),
              })
            }
            onRemove={() => deleteMut.mutate(source.id)}
          />
        ))}
      </div>
    </section>
  );
}

function SourceKindButton({
  active,
  icon,
  label,
  onClick,
  testId,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  testId: string;
}): React.ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={testId}
      className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs"
      style={{
        borderColor: active ? "var(--accent)" : "var(--line)",
        background: active ? "var(--accent-tint-2)" : "transparent",
      }}
    >
      {icon}
      {label}
    </button>
  );
}

function DigestSourceRow({
  source,
  busy,
  onToggle,
  onRemove,
}: {
  source: DigestSourceSummary;
  busy: boolean;
  onToggle: () => void;
  onRemove: () => void;
}): React.ReactNode {
  const { t } = useTranslation();
  const value = source.kind === "rss" ? source.url : source.prompt;
  return (
    <div
      className="flex items-start justify-between gap-3 border-b px-3 py-2 text-xs last:border-b-0"
      style={{ borderColor: "var(--line)" }}
      data-testid={`digest-source-row-${source.id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{source.name}</span>
          <span
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]"
            style={{ background: "var(--accent-tint-2)" }}
          >
            {source.kind === "rss" ? (
              <Rss className="size-3" />
            ) : (
              <Sparkles className="size-3" />
            )}
            {source.kind}
          </span>
          <span className="text-muted-foreground">
            {source.enabled
              ? t("settings.digest.enabled")
              : t("settings.digest.disabled")}
          </span>
          {source.pull_status && source.pull_status !== "idle" && (
            <span className="font-mono text-[10px] text-muted-foreground">
              {source.pull_status}
            </span>
          )}
        </div>
        <div className="mt-1 truncate text-[11px] text-muted-foreground">
          {value || "-"}
        </div>
        {source.last_error && (
          <div className="mt-1 text-[11px]" style={{ color: "var(--danger, #c0392b)" }}>
            {source.last_error}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={onToggle}
          disabled={busy}
          title={
            source.enabled
              ? t("settings.digest.disable")
              : t("settings.digest.enable")
          }
          data-testid={`digest-source-toggle-${source.id}`}
          className="rounded border p-1 disabled:opacity-50"
          style={{ borderColor: "var(--line)" }}
        >
          <Power className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          title={t("settings.digest.remove")}
          data-testid={`digest-source-remove-${source.id}`}
          className="rounded border p-1 disabled:opacity-50"
          style={{ borderColor: "var(--line)" }}
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

function sourcePayloadFromSummary(
  source: DigestSourceSummary,
  enabled: boolean,
): DigestSourcePayload {
  return source.kind === "rss"
    ? {
        name: source.name,
        kind: "rss",
        enabled,
        url: source.url ?? "",
      }
    : {
        name: source.name,
        kind: "prompt",
        enabled,
        prompt: source.prompt ?? "",
      };
}

function apiErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "detail" in err) {
    const detail = (err as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return fallback;
  }
  return fallback;
}
