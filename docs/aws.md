# AWS deployment direction

The GitHub-backed design supersedes the earlier hosted API and database plan.
Round one requires no AWS resources or RDS. GitHub Actions runs the trusted
broker and deploys the static dashboard to GitHub Pages.

See [the design document](design.md) for the initial setup, delivery phases, and
possible later small discussion server. That extension would use one small AWS
instance, FastAPI, SQLModel, SQLite on persisted disk, and automated off-instance
backups. It would provide communication while GitHub retains task authority.

Exact instance sizing, infrastructure, restore procedures, and a GitHub Actions
deployment workflow for that server should be specified only if the extension
is selected. No AWS resources have been provisioned.
