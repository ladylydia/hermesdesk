# Release QA checklist

Run this whole checklist on **both** OS images before tagging a release.
Ideally use clean VMs (Hyper-V or VirtualBox) so leftover state from
previous runs doesn't mask install bugs.

## Target images

| Image                    | Why                                        |
|--------------------------|--------------------------------------------|
| Windows 10 22H2 x64      | Lowest supported. Has WebView2 evergreen.  |
| Windows 11 23H2 x64      | Default for new PCs.                       |
| Windows 10 LTSC 2021     | (Optional) Stripped image; catches missing OS bits. |

## A. Install

- [ ] Download `.msi` from GitHub Releases over a normal browser
- [ ] SmartScreen status:
  - [ ] OV-only build: shows "More info" -> publisher = HermesDesk
  - [ ] After warm-up: no warning at all
- [ ] Double-click the `.msi`
  - [ ] No UAC prompt (per-user install)
  - [ ] Finishes within 60s on a clean SSD
  - [ ] Start Menu has "HermesDesk"
  - [ ] No desktop shortcut unless we ship one (we don't, by design)
- [ ] Disk usage at `%LOCALAPPDATA%\HermesDesk` is between 80 and 200 MB

## B. First launch (cold)

- [ ] App opens within 3 seconds (splash visible)
- [ ] Splash transitions to onboarding (no chat UI yet, no key)
- [ ] No console window flashes or stays open
- [ ] Tray icon appears
- [ ] `%LOCALAPPDATA%\HermesDesk\logs\hermesdesk.log` exists and contains
      `python ready on port NNNN`

## C. Onboarding wizard (zero-jargon happy path)

- [ ] Welcome screen wording reads naturally to a non-tech tester
- [ ] "Pick a brain" - tap "Free starter" -> "Get your access pass"
- [ ] "Open OpenRouter in browser" - opens default browser, NOT in-app
- [ ] Paste a known-good key, hit "Save and continue":
  - [ ] Validation succeeds within 3s
  - [ ] No plaintext key in `%LOCALAPPDATA%\HermesDesk\settings.json`
  - [ ] `cmdkey /list:HermesDesk*` lists the credential
- [ ] Pick "Helpful" vibe -> "Done" page renders
- [ ] "Open workspace folder" opens `Documents\HermesWork` in Explorer
- [ ] "Start chatting" replaces window with chat UI

## D. Chat sanity

- [ ] Send "hi" - replies within 5s on a typical home connection
- [ ] Drop a `.txt` file into the workspace folder, ask the agent to
      summarize "the file I just dropped" - succeeds
- [ ] Ask the agent to delete a file outside the workspace
      (e.g. `C:\Windows\notepad.exe`) - the jail rejects with a friendly
      error, the file is untouched

## E. Safety / Power user

- [ ] In Settings, attempt to enable Power user - confirmation dialog appears
- [ ] Enable, then ask the agent to run `dir`:
  - [ ] Native Windows dialog appears with the command and CWD
  - [ ] "Deny" leaves the workspace untouched
  - [ ] "Allow this once" runs it; output reaches chat
  - [ ] Re-asking later still re-prompts (no implicit "always allow")
- [ ] Disable Power user, restart - Power-user-only tools no longer
      appear in the agent's tool list

## F. Persistence + restart

- [ ] Quit via tray "Quit" - no orphan `python.exe` in Task Manager
- [ ] Reopen - skips onboarding, lands directly in chat
- [ ] Reboot the VM, open the app - same behavior, key still works

## G. Network allowlist

- [ ] In Power-user mode, ask the agent to fetch `https://example.com`
      - blocked with a clear error message
- [ ] Settings -> add `example.com` to extra hosts -> retry - succeeds

## H. Updates

- [ ] Install v0.1.0
- [ ] Publish v0.1.1 release with bumped version
- [ ] Tray menu -> "Check for updates" finds it
- [ ] Click update -> download progress visible
- [ ] After restart, Settings shows v0.1.1
- [ ] Workspace folder + saved key carried forward

## I. Uninstall

- [ ] Settings -> Apps -> HermesDesk -> Uninstall
- [ ] No UAC prompt
- [ ] Removes `%LOCALAPPDATA%\HermesDesk\` (or leaves only the workspace
      folder under `Documents\` - confirm we never delete user docs)
- [ ] Tray icon disappears
- [ ] Credential Manager entry is removed (or, if not, `Sign out` did it
      before uninstall and we documented the split)

## J. Crash recovery

- [ ] Kill `python.exe` from Task Manager - Tauri shows "Helper crashed,
      restart?" within 5s
- [ ] Click restart - chat resumes

## K. Accessibility smoke

- [ ] Tab order through onboarding is sensible
- [ ] Screen reader (NVDA) reads each step's heading and primary action
- [ ] System "high contrast" theme doesn't break the wizard

---

## Sign-off

| Tester | OS              | Date | Build | Notes |
|--------|-----------------|------|-------|-------|
|        | Win 10 22H2     |      |       |       |
|        | Win 11 23H2     |      |       |       |
