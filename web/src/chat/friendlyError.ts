import type { Locale } from "../lib/i18n-core";

const ZH = {
  permission:
    "我现在没有权限处理这个文件。你可以先把文件拖进来，或换一个我能访问的位置。",
  stream: "回复到一半断开了。你可以再试一次，我会接着帮你处理。",
  timeout: "这一步等得有点久。我没能完成它，你可以稍后再试一次。",
  network: "我暂时连不上需要的服务。你可以检查网络后再试一次。",
  json: "本机助手返回的内容我没读懂。请重启应用，或重新构建 Python bundle 后再试。",
  generic: "这个步骤我没成功。你可以换个说法，或把要处理的文件拖进来再试。",
};

const EN = {
  permission:
    "I do not have permission to handle that file yet. You can drag it in here, or choose a location I can access.",
  stream: "I lost the reply halfway through. Please try again, and I can pick it back up.",
  timeout: "That step took too long and did not finish. Please try again in a moment.",
  network: "I cannot reach the service I need right now. Please check the network and try again.",
  json: "The local assistant sent back something I could not read. Please restart the app or rebuild the Python bundle.",
  generic: "I could not finish that step. Try phrasing it another way, or drag the file in here and I can try again.",
};

export function friendlyChatError(raw: string, locale: Locale): string {
  const text = raw.trim();
  if (!text) return locale === "en" ? EN.generic : ZH.generic;
  const lower = text.toLowerCase();
  const copy = locale === "en" ? EN : ZH;

  if (
    lower.includes("permission denied") ||
    lower.includes("access is denied") ||
    lower.includes("拒绝访问") ||
    lower.includes("没有权限")
  ) {
    return copy.permission;
  }
  if (
    lower.includes("stream failed") ||
    lower.includes("stream_closed") ||
    lower.includes("stream closed")
  ) {
    return copy.stream;
  }
  if (lower.includes("timeout") || lower.includes("timed out") || lower.includes("超时")) {
    return copy.timeout;
  }
  if (
    lower.includes("network") ||
    lower.includes("connection") ||
    lower.includes("unreachable") ||
    lower.includes("连不上")
  ) {
    return copy.network;
  }
  if (
    lower.includes("non-json") ||
    lower.includes("json") ||
    lower.includes("error decoding response body")
  ) {
    return copy.json;
  }
  return copy.generic;
}
