# VSCodium Copilot Integration Investigation Report

## Objective
To enable GitHub Copilot and Copilot Chat within VSCodium (specifically for use in `vscode-bisect`), bypassing the restrictions that typically limit these extensions to official VS Code builds.

## Attempt 1: VSCodium Insiders & API Spoofing

### Strategy
We attempted to run VSCodium Insiders runs and "spoof" the environment to look like VS Code by modifying `product.json`.

### Findings & Failures
*   **API Proposal Mismatch**: The primary blocker was the mismatch between the VSCodium build's `product.json` and the requirements of the Copilot Chat extension.
    *   Copilot Chat requires a specific set of "proposed APIs" (e.g., `inlineCompletions`, `chatParticipants`, `interactive`).
    *   VSCodium disables these by default or lacks the specific proposal versions expected by the extension.
    *   **Error**: `Extension 'GitHub.copilot-chat' CANNOT use API proposal: ...`
*   **Authentication Flow**: Even when API proposals were manually injected, the GitHub authentication flow failed to complete.
    *   The extension attempts to open a browser for OAuth.
    *   The callback redirects to `vscode://` protocol.
    *   VSCodium listens on `vscodium://`, causing the callback to be dropped or requiring manual token handling which the extension often rejected.

## Attempt 2: Community Guide (Discussion #1487)

Ref: [VSCodium Discussion #1487](https://github.com/VSCodium/vscodium/discussions/1487)

### Strategy A: The "Downgrade" Method
*   **Concept**: Install an older version of Copilot Chat (v0.23) known to have looser API requirements and stability.
*   **Result**: 
    *   Successfully installed v0.23.
    *   Authentication was inconsistent. Sometimes it showed "Signed In", but often failed connectivity checks (`Got 0 sessions`).
    *   **Auto-Update Issue**: VSCodium would immediately auto-update the extension to the broken latest version unless `extensions.autoUpdate` was explicitly disabled.

### Strategy B: The "Superset" API Injection
*   **Concept**: Analyze logs to find *every* missing API proposal complained about by the latest Copilot Chat (v0.33+) and inject them all into `product.json`.
*   **Injected Proposals**: `dataChannels`, `chatStatusItem`, `chatSessionsProvider`, `terminalExecuteCommandEvent`, `documentFiltersExclusive`, and others.
*   **Critical Missing Link**: We discovered that modifying `extensionEnabledApiProposals` was not enough; we also had to whitelist the *extension ID itself* in `extensionAllowedProposedApi`.
*   **Result**: This resolved the "Cannot use API proposal" hard errors, allowing the extension to activate, but Authentication remained broken.

### Strategy C: Protocol Handler Patching
*   **Concept**: To fix the authentication callback, we patched the macOS `Info.plist` of the VSCodium bundle to explicitly register the `vscode` URL scheme.
*   **Result**: This was the most robust fix for the redirect loop. The browser callback correctly prompted to open VSCodium.

### Strategy D: The "Kelzenberg" Split-Install
*   **Concept**: 
    1.  Install Copilot Chat v0.23 (Old).
    2.  Sign In (Success due to older, simpler requirements).
    3.  Force-Upgrade to Latest via CLI (`--install-extension ... --force`) while keeping the VSCodium process open or preserving the auth DB.
*   **Result**: 
    *   The upgrade worked technically.
    *   **Split-Brain Failure**: The upgrade resulted in *two* extension folders co-existing (`GitHub.copilot-chat` vs `github.copilot-chat`), likely due to case-sensitivity handling in the script vs marketplace.
    *   Even after removing the duplicate, the UI state became desynchronized from the internal Auth state (Diagnostics showed "Signed In", UI showed "Sign In").

## Conclusion
Getting Copilot Chat to work reliably in VSCodium is currently a fragile game of "Whac-A-Mole":
1.  **API Proposals**: Require constant maintenance of `product.json` as the extension updates.
2.  **Authentication**: Requires binary patching (`Info.plist`) or specific old versions to bootstrap.
3.  **Updates**: Auto-updates break the fragile setup immediately.

While we achieved partial success (activated extension, successful token acquisition), the integration is not stable enough for a "set and forget" usage pattern in the bisect tool.
