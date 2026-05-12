export interface DesktopDeliveryMessage {
  title: string;
  message: string;
}

export interface DesktopDeliveryNotice {
  id: string;
  title: string;
  preview: string;
}

const DEFAULT_TITLE = "Scheduled task";
const MAX_PREVIEW_CHARS = 140;

function truncatePreview(value: string): string {
  const chars = Array.from(value.trim());
  if (chars.length <= MAX_PREVIEW_CHARS) return chars.join("");
  return `${chars.slice(0, MAX_PREVIEW_CHARS).join("")}...`;
}

export function createDesktopDeliveryNotice(
  message: DesktopDeliveryMessage,
  timestamp: number,
  fallbackTitle = DEFAULT_TITLE,
): DesktopDeliveryNotice {
  return {
    id: `desktop-delivery-${timestamp}`,
    title: message.title.trim() || fallbackTitle,
    preview: truncatePreview(message.message || ""),
  };
}
