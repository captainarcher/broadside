---
status: resolved
trigger: "PiP courtroom sketch overlay in FFmpeg assembly pipeline not showing up in final video"
created: 2026-07-24T00:00:00Z
updated: 2026-07-24T00:00:00Z
---

## Current Focus

hypothesis: n/a - resolved
test: n/a
expecting: n/a
next_action: n/a

## Symptoms

expected: Courtroom sketch illustration overlaid as PiP in upper-right of talk scenes
actual: Overlay invisible in final output video
errors: None (ffmpeg exits 0)
reproduction: Run assemble_timeline with illustrations present
started: Since PiP feature was added

## Eliminated

- hypothesis: webp format not supported by ffmpeg
  evidence: Direct ffmpeg command with same webp works fine
  timestamp: 2026-07-24

- hypothesis: filter_complex syntax error
  evidence: Filter graph structure was correct, issue was semantic not syntactic
  timestamp: 2026-07-24

## Evidence

- timestamp: 2026-07-24
  checked: _prepare_talk_scene overlay branch (line 111)
  found: overlay filter uses shortest=1; webp is a single still frame so overlay duration = 1 frame
  implication: shortest=1 tells ffmpeg to end overlay when shortest input ends - the still image ends immediately

- timestamp: 2026-07-24
  checked: Input arguments for illustration
  found: No -loop 1 flag on illustration input; still image treated as single-frame input
  implication: Without looping, the image stream ends after one frame

- timestamp: 2026-07-24
  checked: Working direct command provided by user
  found: No shortest=1 in working command; same filter structure otherwise works
  implication: Confirms shortest=1 is the culprit

## Resolution

root_cause: Two issues combined to make the PiP overlay invisible:
  1. `shortest=1` on the overlay filter caused the overlay to end when the shortest input (the still webp image = 1 frame) ended
  2. No `-loop 1` flag on the illustration input, so the still image was treated as a single-frame stream

fix: Three changes to _prepare_talk_scene():
  1. Removed `shortest=1` from the overlay filter (line 111)
  2. Added `-loop 1` before the illustration `-i` argument (line 118) to make the still image loop continuously
  3. Added `-shortest` as an output flag (line 128) so encoding stops when the main video ends (not the infinite loop)

verification: Extracted frame 90 from test output - PiP overlay clearly visible in upper-right corner showing courtroom sketch over the news desk scene

files_changed:
  - broadside/assemble/ffmpeg.py
