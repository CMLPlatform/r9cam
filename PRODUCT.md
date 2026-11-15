# Product

## Users

Lab operators who set up a capture station: a Raspberry Pi with a camera module that photographs lab work and streams a preview. They are not developers. They often work from a phone on the same LAN as the Pi, standing next to the hardware, sometimes with one free hand. They use the UI a few times per station, mostly at setup, then rarely.

## Surfaces

The UI is in Operate mode: it helps someone do a task, then gets out of the way.

- Homepage: device status (paired or not, camera present, storage, errors) and a live camera preview.
- Setup (`/setup`): pairing with the R9lab backend using the short code shown on the page, and managing local API keys.

## Principles

- Status first. Show what is wrong and the next step to fix it, in plain words, before any detail.
- One task per screen. Pairing and key management stay on `/setup`; the homepage only reports.
- Phone first. Layouts work at 360 px wide, touch targets are at least 44 px, and nothing needs hover.
- Safe by default. Secrets such as API keys are shown once and masked afterwards. Destructive actions ask for confirmation.

## Constraints

- Runs offline on a lab LAN. No third-party CDNs, fonts, analytics or remote scripts; the device serves every asset.
- WCAG 2.2 AA: contrast, keyboard use, visible focus, a label on every control, status never conveyed by colour alone.
- The preview degrades cleanly when the camera is absent or the stream is slow.

## Languages

English is the source language, and the pages and the errors they show also come in Dutch (see CONTRIBUTING.md for adding strings). Keep user-facing strings out of code logic so they can be extracted. Leave room for text that grows by about 30 percent. Do not build sentences from fragments, and format dates, times and numbers by locale. Give each error a stable code beside the translated text so support can find it.

## Voice

Plain, short, literal. Say what happened and what to do. No marketing, no jokes, no jargon such as "relay" without a one-line explanation.
