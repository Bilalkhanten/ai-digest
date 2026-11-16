# AI repo digest

Every day a GitHub Actions workflow picks one popular, recently active AI repo
(rotating topics such as `llm`, `ai-agents`, `rag`, `mcp`), forks it into your
account, and commits a short digest entry to this repo. The fork and the commit
each show up on your contribution graph. See [INDEX.md](INDEX.md) for the log.

## Setup (about 10 minutes)

1. **Create a public repo** on GitHub called `ai-digest` (default branch `main`)
   and upload everything in this folder, including the hidden `.github` folder.
2. **Create a token**: GitHub > Settings > Developer settings > Personal access
   tokens > Tokens (classic) > Generate new token. Tick only the `public_repo`
   scope and set an expiry (90 days is a sensible choice; calendar a renewal).
3. **Add secrets** in the repo under Settings > Secrets and variables > Actions:
   - `FORK_PAT` (required): the token from step 2.
   - `ANTHROPIC_API_KEY` (optional): from the Anthropic Console. Enables a short
     Claude-written summary in each digest. Without it the digest still lists the
     repo's metadata. This is API usage, billed separately from a claude.ai plan;
     one small summary a day costs very little.
4. **Test it**: Actions tab > "Daily AI repo fork" > Run workflow, and tick
   `dry_run`. The log shows the repo it would pick. Then run it again with
   `dry_run` unticked to fork and commit for real.
5. **Check your profile** after a run. The contribution graph can lag, and dates
   are in UTC.

## Notes

- The commit author is set to your GitHub noreply address (`ID+login@users.noreply.github.com`),
  which is what lets the commit count toward your graph.
- Forking counts as a contribution; commits made inside a fork do not.
- GitHub disables scheduled workflows in a public repo after 60 days without
  repo activity. The daily digest commit should keep it active; check the
  Actions tab now and then.
- Tuning (environment variables in the workflow): `MIN_STARS` (default 100),
  `MAX_AGE_DAYS` (default 30), `CLAUDE_MODEL`.
- It forks once a day and keeps `default_branch_only` on to stay light. Don't
  raise the frequency; GitHub's acceptable-use rules target bulk automated activity.
- Revoke the token if you stop using this.

## Run locally

```bash
DRY_RUN=1 python3 scripts/daily_fork.py        # pick only, no token needed
GH_TOKEN=ghp_xxx python3 scripts/daily_fork.py  # fork and write files
```
