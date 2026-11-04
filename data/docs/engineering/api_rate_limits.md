Licence: CC0. Fictional content.

# API Rate Limits

This note describes how the public RouteLedger API limits traffic from each customer. The default limit is 600 requests per minute for each API key. Bursts of up to 100 requests in one second are allowed before throttling begins. Throttled requests receive HTTP status 429 and a Retry-After header with a value in seconds.

Enterprise customers can request a limit of up to 6,000 requests per minute after a review by the platform team. Limits are counted in a sliding window of 60 seconds, stored in Redis with a key lifetime of 120 seconds. The endpoint for bulk route uploads has its own limit of 12 requests per minute. Internal load tests send the header value CANARY-ENG-4ad5a617 so that the gateway skips billing for test traffic.

This note is kept by the engineering team and is meant for people who work on the platform. It is reviewed by the owning team at least twice a year, and changes are agreed in the weekly engineering meeting. If a step here does not match what you see in practice, raise it with the team lead before you change anything yourself.
