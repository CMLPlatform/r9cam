set dotenv-load := true

# Task runner: https://just.systems. `just` lists the recipes, `just <name>` runs one.
#
# Each stack's recipes are in just/, prefixed (`py-`) because
# imports share one namespace, except the few only one kind has, such as `pipeline` or `up`.
import? 'just/python.just'

# List the recipes (what a bare `just` runs).
default:
    @just --list

# The stack checks CI runs. `just hooks` runs the git hooks, which CI also runs.
check:
    @just py-check
    @if just --show local-check >/dev/null 2>&1; then just local-check; fi

# Fix and format every stack here, as each stack's `fmt` recipe does.
fmt:
    @just py-fmt

# The checks workflow skips the hooks in its SKIP list, which the stack workflows run
# instead. Here they all run, so this can fail where the checks workflow passes.

# Run every git hook over the whole repo, not just staged files.
hooks:
    prek run -a

# Protect the default branch (no deletion, no force-push, linear history, PRs squash-merged after the always-on checks pass and one approval) and the v* tags. Turn on secret scanning with push protection, private vulnerability reporting, CodeQL default setup and Dependabot alerts. Safe to rerun.
repo-settings:
    #!/usr/bin/env bash
    set -euo pipefail
    err=$(mktemp)
    trap 'rm -f "$err"' EXIT
    fail() {
        cat "$err" >&2
        grep -qE 'HTTP (403|404)' "$err" && echo "Rulesets on a private repo need a paid GitHub plan (or the repo does not exist, or you lack admin rights)." >&2
        grep -q 'must be part of the ruleset source' "$err" && echo "The main ruleset lets the Renovate app bypass the review, and GitHub accepts that only once the app is installed on this repo: add it at https://github.com/apps/renovate, then rerun." >&2
        exit 1
    }
    # Merge-method switches live on the repo itself; the ruleset also limits the PR button.
    gh api -X PATCH repos/{owner}/{repo} -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false -F delete_branch_on_merge=true -F web_commit_signoff_required=true >/dev/null 2>"$err" || fail
    # Push protection refuses a push that holds a known secret format, before it reaches the repo.
    # A private repo without Secret Protection refuses this, so it warns instead of failing.
    if gh api -X PATCH repos/{owner}/{repo} -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled' >/dev/null 2>"$err"; then
        echo "Turned on secret scanning and push protection."
    else
        echo "Warning: secret scanning could not be turned on (a private repo needs Secret Protection): $(cat "$err")" >&2
    fi
    # Adopt an existing ruleset by name, else one with the same target that protects the same
    # refs as the file, updating it in place. The list has no conditions, so each candidate is read.
    for name in main main-checks tags; do
        file=.github/rulesets/$name.json
        case "$name" in
            main) want='["~DEFAULT_BRANCH"]' filter='.[] | select(.target == "branch" and (.name | test("checks?") | not)) | .id' ;;
            main-checks) want='["~DEFAULT_BRANCH"]' filter='.[] | select(.target == "branch" and (.name | test("checks?"))) | .id' ;;
            tags) want='["refs/tags/v*"]' filter='.[] | select(.target == "tag") | .id' ;;
        esac
        id=$(gh api "repos/{owner}/{repo}/rulesets?includes_parents=false" --jq "first(.[] | select(.name == \"$name\") | .id) // empty" 2>"$err") || fail
        if [ -z "$id" ]; then
            candidates=$(gh api "repos/{owner}/{repo}/rulesets?includes_parents=false" --jq "$filter" 2>"$err") || fail
            for candidate in $candidates; do
                same=$(gh api "repos/{owner}/{repo}/rulesets/$candidate" --jq ".conditions.ref_name.include == $want" 2>"$err") || fail
                if [ "$same" = true ]; then
                    id=$candidate
                    break
                fi
            done
        fi
        if [ -n "$id" ]; then
            gh api -X PUT "repos/{owner}/{repo}/rulesets/$id" --input "$file" >"$err" 2>&1 || fail
            echo "Updated ruleset '$name' ($id)."
        else
            # gh prints GitHub's reason for a refusal on stdout, so fail() needs both.
            gh api -X POST repos/{owner}/{repo}/rulesets --input "$file" >"$err" 2>&1 || fail
            echo "Created ruleset '$name'."
        fi
    done
    # SECURITY.md sends reports to a private security advisory, which this turns on.
    gh api -X PUT repos/{owner}/{repo}/private-vulnerability-reporting >/dev/null 2>"$err" || fail
    echo "Turned on private vulnerability reporting."
    # CodeQL default setup scans every PR and push to main.
    if gh api -X PATCH repos/{owner}/{repo}/code-scanning/default-setup -f state=configured >"$err" 2>&1; then
        echo "Turned on CodeQL default setup."
    else
        echo "Warning: CodeQL default setup could not be turned on, so code scanning stays off: $(cat "$err")" >&2
    fi
    # Dependabot alerts let Renovate open security PRs and turn on the dependency graph.
    gh api -X PUT repos/{owner}/{repo}/vulnerability-alerts >/dev/null 2>"$err" || fail
    echo "Turned on Dependabot alerts."
    if [ -f .github/first-release.md ]; then echo "First-release checklist: gh issue create --title 'First release' --body-file .github/first-release.md"; fi
# Set the GitHub About box from your answers: description and a topic per stack. Adds topics, never removes yours. Safe to rerun.
repo-about:
    gh repo edit --description 'Raspberry Pi Camera plugin for R9lab platform' --add-topic python

# A repo's own recipes that copier updates never touch. A `local-check` recipe there runs
# at the end of `just check`.
import? 'just/local.just'
