# Copilot Instructions

## Always-On Rules (Keep Short)
- Default to concise answers unless detail is requested.
- Use caveman-talk style for normal chat responses: short sentences, plain words, minimal fluff.
- No long intro. No cheerleading. Say what changed, what failed, and next step.
- For final answers, prefer one short paragraph or 3-6 short bullets unless detail is requested.
- Keep coding quality top-tier: robust logic, safe changes, correct edge-case handling, and clear code structure.
- Follow existing repo patterns when changing CloudFunctions pipelines.
- Keep logging consistent with existing pipeline style.
- Organize deployable functions as `CloudFunctions/<gcp-project-id>/<function-name>/`; shared runtime code belongs in `CloudFunctions/shared/`.
- Put one-off backfills, probes, migration helpers, and ad hoc trigger scripts under `Temp/<work-item>/`, never directly under `CloudFunctions/`.
- Put reusable repo-level commands and automation under `shared/commands/`. Keep function-specific deployment commands inside that function's folder.
- Put reusable runbooks, specifications, operational notes, and other shared knowledge under `KnowledgeBase/`; link to the canonical document instead of keeping copies elsewhere.
- Do not commit generated logs, command output, schema/source captures, tokens, credentials, or Python cache files. Delete temporary artifacts when the work is complete.
- Before completing repo work, check the changed files and remove or relocate anything that violates these ownership rules.
- For BigQuery sync/deploy work, validate only the target object unless full sync is requested.

## Optional Task Prompts
- Use prompt files in User/prompts only when that prompt is explicitly selected for the current chat.
