import { useState, useCallback, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { hideCaptureOverlay } from "./capture-api";

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function OverlayWindow() {
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [sel, setSel] = useState<Rect | null>(null);
  const [capturing, setCapturing] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      // Ignore right click.
      if (e.button !== 0) return;
      e.preventDefault();
      const pos = { x: e.clientX, y: e.clientY };
      setStart(pos);
      setSel(null);
    },
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!start) return;
      const cur = { x: e.clientX, y: e.clientY };
      const x = Math.min(start.x, cur.x);
      const y = Math.min(start.y, cur.y);
      const w = Math.abs(cur.x - start.x);
      const h = Math.abs(cur.y - start.y);
      setSel({ x, y, w, h });
    },
    [start],
  );

  const onPointerUp = useCallback(
    async (_e: React.PointerEvent) => {
      if (!start || !sel || sel.w < 4 || sel.h < 4) {
        // Too small selection or no selection — cancel.
        setStart(null);
        setSel(null);
        return;
      }
      setStart(null);
      setCapturing(true);

      try {
        await invoke("cmd_capture_region", {
          x: Math.round(sel.x),
          y: Math.round(sel.y),
          w: Math.round(sel.w),
          h: Math.round(sel.h),
        });
      } catch (err) {
        console.error("capture failed:", err);
      } finally {
        setCapturing(false);
        setSel(null);
      }
    },
    [start, sel],
  );

  const onCancel = useCallback(async () => {
    setStart(null);
    setSel(null);
    setCapturing(false);
    try {
      await hideCaptureOverlay();
    } catch {
      // fallback
    }
  }, []);

  // Capture on document so Esc always cancels regardless of focus.
  useEffect(() => {
    const onDocKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      void onCancel();
    };
    document.addEventListener("keydown", onDocKey, true);
    return () => document.removeEventListener("keydown", onDocKey, true);
  }, [onCancel]);

  useEffect(() => {
    overlayRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 select-none outline-none"
      style={{ touchAction: "none" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      tabIndex={-1}
    >
      {/* Semi-transparent dark mask */}
      <div className="absolute inset-0 bg-black/30" />

      {/* Clear area for the selection rectangle */}
      {sel && sel.w > 0 && sel.h > 0 && (
        <>
          {/* Clear cutout — four surrounding masks */}
          <div
            className="absolute bg-black/30"
            style={{ top: 0, left: 0, right: 0, height: sel.y }}
          />
          <div
            className="absolute bg-black/30"
            style={{ top: sel.y + sel.h, left: 0, right: 0, bottom: 0 }}
          />
          <div
            className="absolute bg-black/30"
            style={{ top: sel.y, left: 0, width: sel.x, height: sel.h }}
          />
          <div
            className="absolute bg-black/30"
            style={{
              top: sel.y,
              left: sel.x + sel.w,
              right: 0,
              height: sel.h,
            }}
          />

          {/* Selection border */}
          <div
            className="absolute border-2 border-blue-400 pointer-events-none"
            style={{
              left: sel.x - 1,
              top: sel.y - 1,
              width: sel.w + 2,
              height: sel.h + 2,
            }}
          />

          {/* Size indicator */}
          <div
            className="absolute bg-blue-500 text-white text-xs px-1.5 py-0.5 rounded pointer-events-none"
            style={{
              left: sel.x,
              top: Math.max(sel.y - 24, 0),
            }}
          >
            {Math.round(sel.w)} x {Math.round(sel.h)}
          </div>
        </>
      )}

      {/* Hint text */}
      {!sel && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-white/80 text-sm">
            Drag to select a region. Press Esc to cancel.
          </span>
        </div>
      )}

      {/* Capturing overlay */}
      {capturing && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-50">
          <span className="text-white text-sm">Capturing...</span>
        </div>
      )}
    </div>
  );
}
