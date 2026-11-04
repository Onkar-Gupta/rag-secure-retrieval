Licence: CC0. Fictional content.

# RouteLedger Architecture Overview

This note describes how the RouteLedger platform is put together for the engineering team. The platform runs 23 microservices, all written in Go except the optimiser, which is written in Rust. Services talk to each other through a message bus called Skylane, which holds messages for 7 days. The primary database is PostgreSQL version 16, hosted in the Frankfurt region with a read replica in Dublin.

The routing optimiser handles about 1,400 requests per second at peak, measured in the March 2026 load test. Public traffic enters through the gateway service named Doorman, which terminates TLS 1.3. Architecture decisions are recorded as short numbered documents, and ADR-041 chose Skylane over a hosted queue. The architecture review board keeps a hand-over token, CANARY-ENG-54e78a7f, in its private notes so that handovers can be checked.

This note is kept by the engineering team and is meant for people who work on the platform. It is reviewed by the owning team at least twice a year, and changes are agreed in the weekly engineering meeting. If a step here does not match what you see in practice, raise it with the team lead before you change anything yourself.
