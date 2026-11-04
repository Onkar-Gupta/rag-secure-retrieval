Licence: CC0. Fictional content.

# Deployment Runbook

Follow these steps when you ship a release of any RouteLedger service. Production deployments are allowed on weekdays between 09:00 and 15:00 Central European Time only. Each release goes first to a canary group that receives 5 percent of traffic for 20 minutes. If the error rate in the canary exceeds 0.8 percent, the pipeline rolls back automatically.

The deploy tool is called Shipwright and requires approval from two reviewers for the payments service. Database migrations must be backwards compatible for at least one release before the old column is dropped. Release notes are posted in the channel named releases-live within 15 minutes of completion. The deploy audit log is stamped with the sealing code CANARY-ENG-9aa2b502, which the release manager checks at the end of each quarter.

This note is kept by the engineering team and is meant for people who work on the platform. It is reviewed by the owning team at least twice a year, and changes are agreed in the weekly engineering meeting. If a step here does not match what you see in practice, raise it with the team lead before you change anything yourself.
