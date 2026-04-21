import { Routes, Route, Navigate } from "react-router-dom";
import { Welcome } from "./steps/Welcome";
import { PickBrain } from "./steps/PickBrain";
import { GetAccessPass } from "./steps/GetAccessPass";
import { PickVibe } from "./steps/PickVibe";
import { Done } from "./steps/Done";
import { ShellFrame } from "./ShellFrame";

/**
 * Five-step zero-jargon onboarding. Each step component owns its own
 * "Next" button so the flow can validate before advancing.
 *
 * Routes:
 *   /onboarding/welcome
 *   /onboarding/brain
 *   /onboarding/pass
 *   /onboarding/vibe
 *   /onboarding/done
 */
export function Wizard() {
  return (
    <ShellFrame>
      <Routes>
        <Route path="welcome" element={<Welcome />} />
        <Route path="brain" element={<PickBrain />} />
        <Route path="pass" element={<GetAccessPass />} />
        <Route path="vibe" element={<PickVibe />} />
        <Route path="done" element={<Done />} />
        <Route path="*" element={<Navigate to="welcome" replace />} />
      </Routes>
    </ShellFrame>
  );
}
