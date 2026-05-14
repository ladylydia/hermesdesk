import type { Locale } from "../lib/i18n-core";
import type { SessionRow } from "./chat-api";

export type SessionKind = "reminder" | "file" | "image" | "chat";
export type SessionIcon = "alarm" | "file" | "image" | "message";

export interface SessionPresentation {
  label: string;
  group: string;
  kind: SessionKind;
  icon: SessionIcon;
}

function textOf(session: SessionRow): string {
  return `${session.title ?? ""} ${session.preview ?? ""}`.trim();
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function groupFor(session: SessionRow, locale: Locale, now: Date): string {
  const ts = session.last_active ?? session.started_at;
  if (!ts) return locale === "en" ? "Recent" : "最近";
  const date = new Date(ts > 1e12 ? ts : ts * 1000);
  if (isSameLocalDay(date, now)) return locale === "en" ? "Today" : "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameLocalDay(date, yesterday)) return locale === "en" ? "Yesterday" : "昨天";
  return locale === "en" ? "Recent" : "最近";
}

function compactReminderLabel(text: string, locale: Locale): string {
  const lower = text.toLowerCase();
  if (locale === "en") {
    if (lower.includes("water")) return "Water reminder";
    if (lower.includes("rest") || lower.includes("break")) return "Break reminder";
    if (lower.includes("sleep") || lower.includes("bed")) return "Sleep reminder";
    if (lower.includes("meeting")) return "Meeting reminder";
    return "Reminder";
  }
  if (text.includes("喝水")) return "喝水提醒";
  if (text.includes("休息")) return "休息提醒";
  if (text.includes("睡觉") || text.includes("睡眠")) return "睡觉提醒";
  if (text.includes("会议")) return "会议提醒";
  const match = text.match(/提醒(?:我)?(.{1,12})/);
  return match?.[1]?.trim() ? `${match[1].replace(/[。！？?!.，,]/g, "")}提醒` : "提醒";
}

function kindFor(text: string): SessionKind {
  const lower = text.toLowerCase();
  if (
    lower.includes("提醒") ||
    lower.includes("remind") ||
    lower.includes("reminder") ||
    lower.includes("scheduled task")
  ) {
    return "reminder";
  }
  if (
    lower.includes(".png") ||
    lower.includes(".jpg") ||
    lower.includes(".jpeg") ||
    lower.includes(".webp") ||
    lower.includes(".gif") ||
    lower.includes("图片") ||
    lower.includes("image") ||
    lower.includes("screenshot")
  ) {
    return "image";
  }
  if (
    lower.includes("\\") ||
    lower.includes("/") ||
    lower.includes(".pdf") ||
    lower.includes(".doc") ||
    lower.includes(".txt") ||
    lower.includes("文件") ||
    lower.includes("file")
  ) {
    return "file";
  }
  return "chat";
}

function labelFor(session: SessionRow, kind: SessionKind, locale: Locale): string {
  const raw = ((session.title && session.title.trim()) || session.preview || session.id.slice(0, 8)).trim();
  const lower = raw.toLowerCase();
  if (kind === "reminder") return compactReminderLabel(raw, locale);
  if (kind === "file") return locale === "en" ? "File help" : "文件处理";
  if (kind === "image") return locale === "en" ? "Image help" : "图片处理";
  if (
    raw === "你是谁？" ||
    raw === "你是谁?" ||
    lower === "who are you?" ||
    lower === "who are you"
  ) {
    return locale === "en" ? "About Nana" : "小娜的自我介绍";
  }
  return raw.replace(/\s+/g, " ").slice(0, 36);
}

export function deriveSessionPresentation(
  session: SessionRow,
  locale: Locale,
  now = new Date(),
): SessionPresentation {
  const text = textOf(session);
  const kind = kindFor(text);
  const icon: SessionIcon =
    kind === "reminder" ? "alarm" : kind === "file" ? "file" : kind === "image" ? "image" : "message";
  return {
    label: labelFor(session, kind, locale),
    group: groupFor(session, locale, now),
    kind,
    icon,
  };
}
