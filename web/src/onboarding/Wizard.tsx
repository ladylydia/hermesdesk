import { Routes, Route, Navigate } from "react-router-dom";
import { SetupMode } from "./steps/SetupMode";
import { Welcome } from "./steps/Welcome";
import { PickBrain } from "./steps/PickBrain";
import { GetAccessPass } from "./steps/GetAccessPass";
import { SectionPlaceholderStep } from "./steps/SectionPlaceholderStep";
import { ShellFrame } from "./ShellFrame";

/**
 * Shell setup wizard. Step order and quick vs full branch match
 * `hermes/hermes_cli/setup.py` (preamble + tts, terminal, gateway, tools, agent); forms can stay minimal until wired.
 */
export function Wizard() {
  return (
    <ShellFrame>
      <Routes>
        <Route path="mode" element={<SetupMode />} />
        <Route path="welcome" element={<Welcome />} />
        <Route path="brain" element={<PickBrain />} />
        <Route path="pass" element={<GetAccessPass />} />
        <Route path="tts" element={<SectionPlaceholderStep id="tts" />} />
        <Route path="terminal" element={<SectionPlaceholderStep id="terminal" />} />
        <Route path="gateway" element={<SectionPlaceholderStep id="gateway" />} />
        <Route path="tools" element={<SectionPlaceholderStep id="tools" />} />
        <Route path="agent" element={<SectionPlaceholderStep id="agent" />} />
        <Route path="vibe" element={<Navigate to="/chat" replace />} />
        <Route path="done" element={<Navigate to="/chat" replace />} />
        <Route path="*" element={<Navigate to="mode" replace />} />
      </Routes>
    </ShellFrame>
  );
}
