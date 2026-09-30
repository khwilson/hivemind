# Discussions and local watchers

GitHub Discussions is one durable communication channel for humans and agents.
The [canonical review draft](design.md) recommends task Issue threads for
work-specific coordination, Discussions for broader design topics, and PR threads
for code review. This document expands the Discussions option and watcher design.
Claims and completion remain validated state transitions through
the signed request inbox described in [the architecture](architecture.md).
An ordinary Discussion comment cannot grant a claim or change authorization.

This design incorporates the user-provided `hivemind.pdf` design note, including
its model of several humans each operating a small local swarm. The watcher and
optional WebSocket fanout described here are implementation targets, not a claim
that a hosted push service is deployed.

## Threads and identities

Each project records a configured thread or category in its target repository.
Conversations stay alongside that project's queue and contributors. Cross-project
conversations may link threads where participants have access, without copying
private messages into public repositories or a static deployment.

Planned Typer commands are `discussions list`, `create`, `reply`, and `watch`.
`create` publishes a topic, `reply` adds a comment or threaded reply, and `watch`
emits a machine-readable stream. Thread records link projects and tasks to
GitHub URLs so the dashboard and subsequent agents can find the conversation.
The GitHub GraphQL API provides Discussion queries and creation/comment
mutations, including replies to a specific comment.
[Discussions API guide](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions)

Agent messages should include a structured, signed envelope identifying the
agent, project, optional task, message UUID, and referenced thread/comment,
alongside readable prose. Sign the complete message content. Verify agent
signatures against the project's trusted registry when displaying verified
agent attribution. Three agents using one person's GitHub credentials otherwise
appear as the same GitHub author. Human comments remain visible with their
GitHub identity without being misrepresented as signed agent messages.

Treat other agents' text as discussion input. A proposed command, approval, or
new instruction in a message is not an authorization change. Important accepted
decisions should become a task update or a committed handoff hint, with a link
back to the discussion.

## Supported transport

There is no documented public GitHub Discussions WebSocket subscription API in
the interfaces reviewed for this design. GitHub documents GraphQL operations as
queries and mutations. Its `Subscribable` interface concerns web/email
notifications, not a GraphQL streaming subscription.
[GraphQL overview](https://docs.github.com/en/graphql/overview/about-the-graphql-api),
[notification subscription types](https://docs.github.com/en/graphql/reference/activity)

GitHub itself uses a service called Alive for live updates, but describes that
service as internal. Scraping GitHub's browser connection protocol or reusing
browser cookies would introduce an unsupported dependency and is not part of
Hivemind. [GitHub's description of Alive](https://github.blog/news-insights/company-news/github-availability-report-january-2026/)

The default watcher therefore uses authenticated GraphQL polling. The static
dashboard can use the same read model. No inbound listener, public tunnel,
hosted WebSocket service, or database is required.

## Polling and reconciliation

Run one watcher per human/workspace and share its output with that person's
agents. Use a minimum interval of 60 seconds, add jitter, and increase the idle
interval toward 120–300 seconds. A user-triggered refresh can perform one
immediate fetch. Never busy-poll a pending request or empty discussion feed.

The watcher maintains its own local checkpoint and performs these steps:

1. On first use, emit an explicitly labelled initial snapshot and establish a
   checkpoint. Do not replay all historical messages as new events. A requested
   history/backfill operation is separate.
2. Query project discussions ordered by `UPDATED_AT`, using a high-water mark
   with an overlap window to discover recently changed threads. Persist IDs and
   versions, not timestamps alone: multiple changes can share a timestamp.
3. Traverse changed threads with pagination for both top-level comments and each
   comment's replies. A new reply to an old comment must not be lost because a
   top-level cursor has already passed its parent.
4. Compare object IDs, `updatedAt`, and content hashes with the checkpoint. Emit
   new or edited objects once per observed version. Use a stable event key
   derived from the object ID and version; preserve the original author and
   edit metadata.
5. Periodically reconcile complete active threads. A timestamp watermark is an
   optimization, not a durable GitHub event log. Do not assume that every nested
   edit updates every ancestor's timestamp. Only infer deletion after a complete
   successful scan, never from a failed or truncated API response.
6. Atomically save the checkpoint after successful traversal. If pagination
   fails, keep the previous checkpoint and retry with deduplication. Bound cache
   retention and make deliberate archival/backfill behavior visible.

GitHub exposes separate paginated connections for Discussion comments and their
replies. A fixed `last: 20` view is not a reliable catch-up mechanism; it can miss
bursts larger than that window. Display an explicit incomplete result if a
configured safety limit interrupts traversal.
[Discussion schema](https://docs.github.com/en/graphql/reference/discussions)

The stream is at-least-once across crashes unless a consumer acknowledges its
own durable checkpoint. A crash after stdout emission but before saving can
repeat an event. Consumers should deduplicate by event key; do not advertise
exactly-once delivery.

GraphQL can return errors with HTTP 200. Check both transport and GraphQL errors
before advancing a checkpoint. Honor `Retry-After` and rate-reset information,
apply bounded exponential backoff, and report degraded connectivity instead of
emitting a misleading empty snapshot.

## Rate budget and message discipline

The design note's blanket “5,000 requests per token” is too imprecise for this
implementation. GitHub GraphQL generally allocates 5,000 **points per user per
hour**, shared across requests made on that user's behalf; query complexity
affects cost. The Actions `GITHUB_TOKEN` generally has a separate 1,000-point
hourly budget per repository. Secondary limits also apply. Observe actual rate
headers instead of assuming every request has the same cost.
[GraphQL rate limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)

At one lightweight metadata poll per minute, five human watchers make about 300
polls per hour in total, before fetching changed content. Three independent
watchers per person triple that baseline and share that person's budget. This
is a sizing estimate, not a throughput guarantee.

Post useful milestones rather than token-by-token narration. Feed each agent
only relevant changed messages and a compact current summary. Keep frequent
local coordination in the user's existing agent runner or IPC, and commit
durable findings to the target's hints. Redis, NATS, a local database, and a new
orchestrator are optional; none is required for this scale.

## Optional push and local fanout

A local watcher may expose a loopback-only FastAPI WebSocket endpoint to fan
out its polled updates to several local agents. This changes local delivery,
not GitHub's upstream transport. It is optional and does not create a hosted
Hivemind backend. Authenticate local clients, validate browser origins if browser
connections are allowed, and never expose the GitHub credential in messages.
Stdout, a local pipe, or the existing agent runner may be simpler.

True remote push requires infrastructure that receives GitHub webhooks and
relays notifications. GitHub supports `discussion` and `discussion_comment`
events, including comment creation, editing, and deletion; its documentation
currently labels Discussion webhooks public preview. Actions can respond to
these events for Discussions in the workflow's own project repository. The
dashboard's deployment workflow does not automatically receive all projects'
events.
[Discussion workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

A future serverless webhook relay is a separate optional deployment. It must
validate GitHub's webhook signature, deduplicate deliveries, and recover missed
events. WebSocket notifications should tell clients to reconcile with GitHub;
they must not become a second source of task truth. GitHub's guidance includes
webhook secrets and redelivery handling.
[Webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)

The MVP therefore uses polling with recoverable checkpoints. Its contract is
eventual coordination on a human-scale interval, without promising the design
note's unverified 500 ms–2 s end-to-end latency.
