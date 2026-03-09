import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { FieldBool } from "../components/EnvFields";
import { IconBook, IconClipboard, IconBot, IconPlus, IconEdit, IconTrash, LogoTelegram, LogoFeishu, LogoWework, LogoDingtalk, LogoQQ } from "../icons";
import { safeFetch } from "../providers";
import type { EnvMap } from "../types";
import { envGet, envSet } from "../utils";
import { copyToClipboard } from "../utils/clipboard";
import type { IMBot } from "./im-shared";
import { BOT_TYPE_LABELS, CREDENTIAL_FIELDS, ENABLED_KEY_TO_TYPE, TYPE_TO_ENABLED_KEY } from "./im-shared";

type IMConfigViewProps = {
  envDraft: EnvMap;
  setEnvDraft: (updater: (prev: EnvMap) => EnvMap) => void;
  setNotice: (v: string | null) => void;
  busy: string | null;
  secretShown: Record<string, boolean>;
  onToggleSecret: (k: string) => void;
  currentWorkspaceId: string | null;
  onNavigateToBotConfig?: (presetType?: string) => void;
  apiBaseUrl?: string;
  pendingBots?: IMBot[];
  onPendingBotsChange?: (bots: IMBot[]) => void;
};

export function IMConfigView(props: IMConfigViewProps) {
  const {
    envDraft, setEnvDraft, setNotice, busy,
    onNavigateToBotConfig, apiBaseUrl,
    pendingBots, onPendingBotsChange,
  } = props;
  const { t } = useTranslation();

  const isOnboardingMode = pendingBots !== undefined && onPendingBotsChange !== undefined;

  // API bots (wizard mode only)
  const [apiBots, setApiBots] = useState<IMBot[]>([]);
  const fetchBots = useCallback(async () => {
    if (!apiBaseUrl || isOnboardingMode) return;
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/agents/bots`);
      const data = await res.json();
      setApiBots(data.bots || []);
    } catch { /* ignore */ }
  }, [apiBaseUrl, isOnboardingMode]);
  useEffect(() => { fetchBots(); }, [fetchBots]);

  // Inline editor state (onboarding mode)
  const [editingBotType, setEditingBotType] = useState<string | null>(null);
  const [editingBotIdx, setEditingBotIdx] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<IMBot | null>(null);
  const [revealedSecrets, setRevealedSecrets] = useState<Set<string>>(new Set());

  const openAddBot = (botType: string) => {
    setEditingBotType(botType);
    setEditingBotIdx(null);
    setEditForm({
      id: `${botType}-${Date.now().toString(36)}`,
      type: botType,
      name: BOT_TYPE_LABELS[botType] || botType,
      agent_profile_id: "default",
      enabled: true,
      credentials: {},
    });
    setRevealedSecrets(new Set());
  };

  const openEditBot = (bot: IMBot, idx: number) => {
    setEditingBotType(bot.type);
    setEditingBotIdx(idx);
    setEditForm({ ...bot, credentials: { ...bot.credentials } });
    setRevealedSecrets(new Set());
  };

  const cancelEdit = () => {
    setEditingBotType(null);
    setEditingBotIdx(null);
    setEditForm(null);
  };

  const saveBot = () => {
    if (!editForm || !onPendingBotsChange || !pendingBots) return;
    if (!editForm.id.trim()) return;

    if (editingBotIdx !== null) {
      const updated = [...pendingBots];
      updated[editingBotIdx] = editForm;
      onPendingBotsChange(updated);
    } else {
      onPendingBotsChange([...pendingBots, editForm]);
    }

    // Auto-set the .env enabled flag
    const enabledKey = TYPE_TO_ENABLED_KEY[editForm.type];
    if (enabledKey) {
      setEnvDraft((m) => envSet(m, enabledKey, "true"));
    }

    cancelEdit();
  };

  const deleteBot = (idx: number) => {
    if (!pendingBots || !onPendingBotsChange) return;
    const removed = pendingBots[idx];
    const updated = pendingBots.filter((_, i) => i !== idx);
    onPendingBotsChange(updated);

    // Adjust or cancel the inline editor if indices shifted
    if (editingBotIdx !== null) {
      if (idx === editingBotIdx) {
        cancelEdit();
      } else if (idx < editingBotIdx) {
        setEditingBotIdx(editingBotIdx - 1);
      }
    }

    // If no more bots of this type, clear the .env enabled flag
    if (removed && !updated.some((b) => b.type === removed.type)) {
      const enabledKey = TYPE_TO_ENABLED_KEY[removed.type];
      if (enabledKey) {
        setEnvDraft((m) => envSet(m, enabledKey, "false"));
      }
    }
  };

  const _envBase = { envDraft, onEnvChange: setEnvDraft, busy };
  const FB = (p: { k: string; label: string; help?: string; defaultValue?: boolean }) =>
    <FieldBool {...p} {..._envBase} />;

  const channels = [
    {
      title: "Telegram",
      appType: t("config.imTypeLongPolling"),
      logo: <LogoTelegram size={22} />,
      enabledKey: "TELEGRAM_ENABLED",
      docUrl: "https://t.me/BotFather",
      needPublicIp: false,
    },
    {
      title: t("config.imFeishu"),
      appType: t("config.imTypeCustomApp"),
      logo: <LogoFeishu size={22} />,
      enabledKey: "FEISHU_ENABLED",
      docUrl: "https://open.feishu.cn/",
      needPublicIp: false,
    },
    {
      title: t("config.imWework"),
      appType: t("config.imTypeSmartBot"),
      logo: <LogoWework size={22} />,
      enabledKey: "WEWORK_ENABLED",
      docUrl: "https://work.weixin.qq.com/",
      needPublicIp: true,
    },
    {
      title: t("config.imDingtalk"),
      appType: t("config.imTypeInternalApp"),
      logo: <LogoDingtalk size={22} />,
      enabledKey: "DINGTALK_ENABLED",
      docUrl: "https://open.dingtalk.com/",
      needPublicIp: false,
    },
    {
      title: "QQ 机器人",
      appType: t("config.imTypeQQBot"),
      logo: <LogoQQ size={22} />,
      enabledKey: "QQBOT_ENABLED",
      docUrl: "https://bot.q.qq.com/wiki/develop/api-v2/",
      needPublicIp: false,
    },
    {
      title: "OneBot",
      appType: t("config.imTypeOneBot"),
      logo: <LogoQQ size={22} />,
      enabledKey: "ONEBOT_ENABLED",
      docUrl: "https://github.com/botuniverse/onebot-11",
      needPublicIp: false,
    },
  ];

  const renderBotCard = (bot: IMBot, globalIdx: number) => (
    <div key={bot.id} style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "6px 10px", borderRadius: 6,
      background: "var(--bg-subtle, #f8fafc)", fontSize: 12,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: 3, flexShrink: 0,
        background: bot.enabled ? "#10b981" : "#94a3b8",
      }} />
      <span style={{ fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {bot.name || bot.id}
      </span>
      <span style={{ opacity: 0.4, fontFamily: "monospace", fontSize: 10 }}>{bot.id}</span>
      {isOnboardingMode && (
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <button
            onClick={() => openEditBot(bot, globalIdx)}
            style={{
              padding: "2px 6px", borderRadius: 4, border: "1px solid var(--line)",
              background: "transparent", cursor: "pointer", fontSize: 10, display: "inline-flex", alignItems: "center", gap: 2,
              color: "var(--text2)",
            }}
          ><IconEdit size={10} />{t("config.imInlineEdit")}</button>
          <button
            onClick={() => deleteBot(globalIdx)}
            style={{
              padding: "2px 6px", borderRadius: 4, border: "1px solid var(--line)",
              background: "transparent", cursor: "pointer", fontSize: 10, display: "inline-flex", alignItems: "center", gap: 2,
              color: "#ef4444",
            }}
          ><IconTrash size={10} />{t("config.imInlineDelete")}</button>
        </div>
      )}
      {!isOnboardingMode && (
        <span style={{ marginLeft: "auto", opacity: 0.5, fontSize: 11, whiteSpace: "nowrap" }}>
          Agent: {bot.agent_profile_id}
        </span>
      )}
    </div>
  );

  const renderInlineEditor = (forType: string) => {
    if (!editForm || editingBotType !== forType) return null;

    const fields = CREDENTIAL_FIELDS[forType] || [];
    const isEditing = editingBotIdx !== null;

    return (
      <div style={{
        marginTop: 8, padding: "12px 14px", borderRadius: 8,
        border: "1px solid var(--primary, #3b82f6)",
        background: "var(--bg, #fff)",
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10, color: "var(--primary, #3b82f6)" }}>
          {isEditing ? t("config.imInlineEditTitle") : t("config.imInlineAddTitle")}
        </div>

        <label style={{ display: "block", marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>Bot ID</span>
          <input
            value={editForm.id}
            onChange={(e) => setEditForm({ ...editForm, id: e.target.value.replace(/[^a-z0-9_-]/g, "") })}
            disabled={isEditing}
            placeholder="my-bot"
            style={{
              display: "block", width: "100%", padding: "6px 8px", borderRadius: 6,
              border: "1px solid var(--line)", fontSize: 12, marginTop: 2,
              background: isEditing ? "var(--bg-subtle, #f1f5f9)" : "var(--bg)",
              boxSizing: "border-box",
            }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>Bot Name</span>
          <input
            value={editForm.name}
            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
            placeholder={BOT_TYPE_LABELS[forType] || "My Bot"}
            style={{
              display: "block", width: "100%", padding: "6px 8px", borderRadius: 6,
              border: "1px solid var(--line)", fontSize: 12, marginTop: 2,
              boxSizing: "border-box",
            }}
          />
        </label>

        {fields.map((f) => {
          const val = String(editForm.credentials[f.key] ?? "");
          const secretKey = `${editForm.id}:${f.key}`;
          const isSecret = f.secret && !revealedSecrets.has(secretKey);
          return (
            <label key={f.key} style={{ display: "block", marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>{f.label}</span>
              <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                <input
                  type={isSecret ? "password" : "text"}
                  value={val}
                  onChange={(e) => setEditForm({
                    ...editForm,
                    credentials: { ...editForm.credentials, [f.key]: e.target.value },
                  })}
                  placeholder={f.label}
                  style={{
                    flex: 1, padding: "6px 8px", borderRadius: 6,
                    border: "1px solid var(--line)", fontSize: 12,
                    boxSizing: "border-box",
                  }}
                />
                {f.secret && (
                  <button
                    type="button"
                    onClick={() => setRevealedSecrets((s) => {
                      const next = new Set(s);
                      next.has(secretKey) ? next.delete(secretKey) : next.add(secretKey);
                      return next;
                    })}
                    style={{
                      padding: "4px 8px", borderRadius: 6, border: "1px solid var(--line)",
                      background: "transparent", cursor: "pointer", fontSize: 11, whiteSpace: "nowrap",
                    }}
                  >{isSecret ? "👁" : "🔒"}</button>
                )}
              </div>
            </label>
          );
        })}

        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button
            onClick={saveBot}
            disabled={!editForm.id.trim()}
            style={{
              padding: "5px 14px", borderRadius: 6, border: "none",
              background: "var(--primary, #3b82f6)", color: "#fff",
              cursor: "pointer", fontSize: 12, fontWeight: 600,
              opacity: editForm.id.trim() ? 1 : 0.5,
            }}
          >{t("config.imInlineSave")}</button>
          <button
            onClick={cancelEdit}
            style={{
              padding: "5px 14px", borderRadius: 6,
              border: "1px solid var(--line)", background: "transparent",
              cursor: "pointer", fontSize: 12,
            }}
          >{t("config.imInlineCancel")}</button>
        </div>
      </div>
    );
  };

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="cardTitle">{t("config.imTitle")}</div>
          <div style={{ display: "flex", gap: 6 }}>
            {!isOnboardingMode && onNavigateToBotConfig && (
              <button
                className="btnSmall"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
                  background: "var(--primary, #3b82f6)", color: "#fff", border: "none",
                  padding: "4px 12px", borderRadius: 6, cursor: "pointer", fontWeight: 600,
                }}
                onClick={() => onNavigateToBotConfig()}
              >
                <IconBot size={13} />{t("config.imGoToBotConfig")}
              </button>
            )}
            <button className="btnSmall" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 }}
              onClick={async () => { const ok = await copyToClipboard("https://github.com/anthropic-lab/openakita/blob/main/docs/im-channels.md"); if (ok) setNotice(t("config.imGuideDocCopied")); }}
              title={t("config.imGuideDoc")}
            ><IconBook size={13} />{t("config.imGuideDoc")}</button>
          </div>
        </div>
        <div className="cardHint">
          {isOnboardingMode ? t("config.imHintOnboarding") : t("config.imHint")}
        </div>
        <div className="divider" />

        {!isOnboardingMode && (
          <>
            <FB k="IM_CHAIN_PUSH" label={t("config.imChainPush")} help={t("config.imChainPushHelp")} />
            <div className="divider" />
          </>
        )}

        {channels.map((c) => {
          const botType = ENABLED_KEY_TO_TYPE[c.enabledKey] || "";

          // In onboarding: bots from pendingBots; in wizard: bots from API
          const channelBots = isOnboardingMode
            ? (pendingBots || []).filter((b) => b.type === botType)
            : apiBots.filter((b) => b.type === botType);

          // In onboarding: channel is "enabled" if it has pending bots
          const enabled = isOnboardingMode
            ? channelBots.length > 0
            : envGet(envDraft, c.enabledKey, "false").toLowerCase() === "true";

          return (
            <div key={c.enabledKey} className="card" style={{ marginTop: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div className="row" style={{ alignItems: "center", gap: 10 }}>
                  {c.logo}
                  <span className="label" style={{ marginBottom: 0 }}>{c.title}</span>
                  <span className="pill" style={{ fontSize: 10, padding: "1px 6px", background: "var(--bg-subtle, #f1f5f9)", color: "var(--muted)" }}>{c.appType}</span>
                  {c.needPublicIp && <span className="pill" style={{ fontSize: 10, padding: "1px 6px", background: "var(--warn-bg, #fef3c7)", color: "var(--warn, #92400e)" }}>{t("config.imNeedPublicIp")}</span>}
                  {enabled && (
                    <span className="pill" style={{ fontSize: 10, padding: "1px 6px", background: "rgba(16,185,129,0.12)", color: "#10b981" }}>
                      {channelBots.length} Bot{channelBots.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                {!isOnboardingMode && (
                  <label className="pill" style={{ cursor: "pointer", userSelect: "none" }}>
                    <input style={{ width: 16, height: 16 }} type="checkbox" checked={enabled}
                      onChange={(e) => setEnvDraft((m) => envSet(m, c.enabledKey, String(e.target.checked)))} />
                    {t("config.enable")}
                  </label>
                )}
              </div>
              <div className="row" style={{ alignItems: "center", gap: 6, marginTop: 4 }}>
                <button className="btnSmall"
                  style={{ fontSize: 11, padding: "2px 8px", display: "inline-flex", alignItems: "center", gap: 3 }}
                  title={c.docUrl}
                  onClick={async () => { const ok = await copyToClipboard(c.docUrl); if (ok) setNotice(t("config.imDocCopied")); }}
                ><IconClipboard size={12} />{t("config.imDoc")}</button>
                <span className="help" style={{ fontSize: 11, userSelect: "all", opacity: 0.6 }}>{c.docUrl}</span>
              </div>

              {/* Bot list */}
              <div style={{ marginTop: 8 }}>
                {channelBots.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.5, marginBottom: 2 }}>
                      {t("config.imConfiguredBots")} ({channelBots.length})
                    </div>
                    {channelBots.map((bot) => {
                      const globalIdx = isOnboardingMode
                        ? (pendingBots || []).indexOf(bot)
                        : -1;
                      return renderBotCard(bot, globalIdx);
                    })}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, opacity: 0.4, fontStyle: "italic" }}>
                    {isOnboardingMode ? t("config.imNoBotsOnboarding") : t("config.imNoBots")}
                  </div>
                )}

                {/* Inline editor (onboarding) or redirect button (wizard) */}
                {isOnboardingMode ? (
                  <>
                    {renderInlineEditor(botType)}
                    {editingBotType !== botType && (
                      <button
                        onClick={() => openAddBot(botType)}
                        style={{
                          marginTop: 6, display: "inline-flex", alignItems: "center", gap: 4,
                          padding: "4px 12px", borderRadius: 6, border: "1px dashed var(--line)",
                          background: "transparent", cursor: "pointer", fontSize: 11,
                          color: "var(--primary, #3b82f6)", fontWeight: 500,
                        }}
                      >
                        <IconPlus size={10} />{t("config.imAddBot")}
                      </button>
                    )}
                  </>
                ) : (
                  onNavigateToBotConfig && (
                    <button
                      onClick={() => onNavigateToBotConfig(botType)}
                      style={{
                        marginTop: 6, display: "inline-flex", alignItems: "center", gap: 4,
                        padding: "3px 10px", borderRadius: 6, border: "1px dashed var(--line)",
                        background: "transparent", cursor: "pointer", fontSize: 11,
                        color: "var(--primary, #3b82f6)", fontWeight: 500,
                      }}
                    >
                      <IconPlus size={10} />{t("config.imAddBot")}
                    </button>
                  )
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
