import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { WindowTitleBar } from "./components/WindowTitleBar";
import { I18nProvider } from "./lib/i18n";
import { Wizard } from "./onboarding/Wizard";
import { Settings } from "./advanced/Settings";
import { Splash } from "./Splash";
import { ChatPage } from "./chat/ChatPage";
import { applyFontSize } from "./lib/ui-prefs";
import "./index.css";

applyFontSize();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <BrowserRouter>
        <div className="flex h-full min-h-0 flex-col">
          <WindowTitleBar />
          <div className="min-h-0 flex-1 overflow-hidden">
            <Routes>
              <Route path="/" element={<Splash />} />
              <Route path="/onboarding/*" element={<Wizard />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
      </BrowserRouter>
    </I18nProvider>
  </React.StrictMode>
);
