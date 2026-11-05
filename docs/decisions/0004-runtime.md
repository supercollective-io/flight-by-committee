# ADR 0004: Combine audience input in one authoritative service

Status: **Proposed** · Date: 2026-11-05

## Context

Many phones need to control one aircraft. Letting every browser write directly to the simulator would make conflicts, eligibility and failure recovery difficult to manage.

## Proposal

Use this logical path: phone browsers → coordination service → simulator adapter → one simulator. The service returns compact feedback to phones and the projection. The adapter returns aircraft telemetry. An operator can pause, reset and take over. These boundaries do not require separate processes or machines.

Start by evaluating local operation: serve the app and WebSocket connection from one HTTPS origin on the venue network, with the show machines wired. Prepare trusted certificates, DNS and downloaded assets; test actual phone access. Restrict simulator command access to the show host or isolated control network and verify that audience devices cannot reach it. Phone-facing HTTPS does not protect a separate simulator command port.

As initial tuning values, try phone full-state updates at 10 Hz, aggregation at 20 Hz and expiry after 1 s without fresh input. These are experimental values, not established requirements. Use server time for expiry, clear previous-round state on reset and resynchronise after connection stalls. Define queue freshness explicitly when implementing the protocol; a newly received message may have been delayed in transit.

An independent simulator-side watchdog must survive the coordination process stopping. Rehearse its pause or assisted fallback rather than assuming zero input will stabilise the aircraft. Convert simulator-native units to metric at the adapter boundary.

## Alternatives and trade-offs

Local operation avoids a WAN dependency but requires venue cooperation and tested browser/network setup. A cloud coordinator with an outbound connection from the local simulator bridge may simplify public access; it adds internet dependency. One authority simplifies aggregation but creates an availability dependency.

## Research informing this choice

Sources checked on 5 November 2026; test the exact browser and network configuration used for a show.

- Wake Lock requires a secure context and may be released or denied. Therefore input expiry cannot depend on a phone staying awake. [MDN Wake Lock](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API).
- Chrome documents permission restrictions around sites accessing local networks. This is a reason to test one local HTTPS/WSS origin rather than assume a public page can reach a private simulator address. [Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access).
- WebSocket sends can queue; `bufferedAmount` exposes queued outgoing bytes. Bound or coalesce unsent input and resynchronise after stalls. Increasing sequence numbers alone do not establish freshness. [MDN WebSocket buffering](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/bufferedAmount).
- High-density Wi-Fi needs venue-specific radio, addressing and capacity planning. A server benchmark or broadband speed test is insufficient. [Cisco large-public-network guide](https://www.cisco.com/c/en/us/support/docs/wireless/catalyst-9800-series-wireless-controllers/222000-design-guide-cx-wireless-for-large-pub.html).

For scale intuition only: 500 phones sending 200-byte messages at 10 Hz produce 8 Mbit/s of application payload; 5,000 produce 80 Mbit/s. This excludes return traffic and protocol/radio overhead. It is arithmetic, not a capacity prediction.

## What would change this

Reconsider topology if local HTTPS, venue access or actual joining proves impractical. Select the final deployment from venue evidence. Avoid automatic local/cloud failover until there is a demonstrated need and a clear single-authority handover.
