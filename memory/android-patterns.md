# Android project patterns (finom)

## TODO comments with Jira references

`// todo ANDR-XXXXX some description` is a valid and accepted pattern — it means the issue will be resolved in the linked Jira task. Do **not** flag these as review issues.

## Feature component initialization (DI)

All feature components use a mutable nullable var without thread synchronization. This is **intentional and standard** across the project (confirmed in 6+ components: PhotoViewer, Tags, Dashboard, Chat, Login, Cards).

Do **not** flag missing `@Volatile` or `synchronized` in feature component `companion object` initializers as a review issue.
