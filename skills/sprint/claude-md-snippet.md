## CLAUDE.md Snippet

Add the following to your project's `CLAUDE.md` file to remind Claude about the sprint workflow in every session:

---

## Sprint Workflow

This project uses the `/sprint` skill for development workflow management on top of GitHub Projects v2.

- Requirements are tracked as GitHub Issues with structured acceptance criteria (WHEN/THEN/SHALL format).
- Sprint state — Status, Priority, Size, Iteration — lives as Project fields, not labels.
- Architectural decisions are recorded in `.dev/decisions/`.
- Project lookup is persisted in `.dev/sprint-config.json` (`project_number`, `project_owner`).

Commands:

- `/sprint setup` — discover/create the GitHub Project, configure fields, link this repo
- `/sprint status` — dashboard read from the Project board (current iteration)
- `/sprint plan` — create new requirements as Issues + Project items
- `/sprint refine` — groom a Backlog item into Status: Ready
- `/sprint pick` — claim a Ready item, branch, implement, PR
- `/sprint decide` — record an architectural decision
- `/sprint upgrade` — pull the latest version of the skill from origin
- `/sprint help` — show all commands and subcommands
