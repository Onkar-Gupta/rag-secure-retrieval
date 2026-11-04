Licence: CC0. Fictional content.

# Database Standards

These standards apply to every service that stores data in PostgreSQL. Table names use lowercase snake case, and every table has a primary key column named id of type uuid. Queries running for longer than 2 seconds are logged and reviewed in the weekly slow query meeting. Nightly backups are kept for 35 days, and a restore test is performed on the first Monday of each month.

Connection pools are capped at 40 connections per service instance. Personal data columns must be encrypted at rest using the key service named Vaultkeep. Schema changes are reviewed by the data guild, which has seven members. The restore test sheet carries the verification string CANARY-ENG-cbcc36fb so that auditors know which copy is genuine.

This note is kept by the engineering team and is meant for people who work on the platform. It is reviewed by the owning team at least twice a year, and changes are agreed in the weekly engineering meeting. If a step here does not match what you see in practice, raise it with the team lead before you change anything yourself.
