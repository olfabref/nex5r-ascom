# One Version for the Alpaca Server and camera-app

The Alpaca Server and camera-app share one `vX.Y.Z` Version number and ship in the same Release. They talk over a private HTTP protocol (`/focusarm`, `/capture?ms=`…) that always changes on both sides at once. A shared Version makes compatibility obvious, and lets the Dashboard flag a mismatch.

## Consequences

- Only the Alpaca Server updates from the Dashboard. camera-app is still installed by hand with Sony-PMCA-RE over USB, so after an Update a Version mismatch is expected until the APK is reinstalled.
- A Release can bump camera-app's Version without changing its code, and the other way round.
