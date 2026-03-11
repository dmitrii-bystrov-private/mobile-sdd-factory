# glab — GitLab CLI

Installed: `brew install glab`
Auth: `glab auth login` (gitlab.com)

Common commands:
```
# My open MRs (run from iOS or Android project dir)
cd /Users/d.bystrov/Projects/Finom/finomcommon && glab mr list --assignee=@me
cd /Users/d.bystrov/Projects/Finom/finom && glab mr list --assignee=@me

# MRs awaiting my review
cd /Users/d.bystrov/Projects/Finom/finomcommon && glab mr list --reviewer=@me
cd /Users/d.bystrov/Projects/Finom/finom && glab mr list --reviewer=@me

# View MR details + diff
glab mr view <id>
glab mr diff <id>

# MR comments / notes
glab mr note list <id>

# My open issues
glab issue list --assignee=@me

# Pipeline status for current branch
glab pipeline status

# CI job logs
glab pipeline ci view
```

Note: `--state` flag does not exist in this version of glab. Run all glab commands from the relevant project directory (iOS or Android), not from the assistant directory.
