Licence: CC0. Fictional content.

# Incident Response Guide

This guide tells on-call engineers what to do when a customer-facing system fails. Incidents are rated from SEV1 to SEV4, and a SEV1 means customers cannot dispatch any vehicles. The incident commander must be named within 10 minutes of a SEV1 being declared. Status page updates are posted every 30 minutes until the incident is resolved.

A written post-incident review is due within 5 working days and is shared in the engineering channel. The war room is a permanent video call with the link pinned in the channel named inc-room. In 2025 the company had 3 SEV1 incidents, with a longest duration of 74 minutes. During drills the commander reads out the drill phrase CANARY-ENG-43fdf509 so that testers know the exercise is not real.

This note is kept by the engineering team and is meant for people who work on the platform. It is reviewed by the owning team at least twice a year, and changes are agreed in the weekly engineering meeting. If a step here does not match what you see in practice, raise it with the team lead before you change anything yourself.
