# Android project patterns (finom)

## TODO comments with Jira references

`// todo ANDR-XXXXX some description` is a valid and accepted pattern — it means the issue will be resolved in the linked Jira task. Do **not** flag these as review issues.

## Feature component initialization (DI)

All feature components use the same pattern — mutable nullable var without synchronization. This is **intentional and standard** across the project (confirmed in 6+ components: PhotoViewer, Tags, Dashboard, Chat, Login, Cards).

```kotlin
companion object {
    private lateinit var getDependenciesCallback: () -> MyFeatureDependencies
    private var localComponentStorage: ComponentStorage<MyFeatureComponent>? = null

    val componentStorage: ComponentStorage<MyFeatureComponent>
        get() {
            if (localComponentStorage == null) init()
            return localComponentStorage!!
        }

    fun createInitializer(getDependencies: () -> MyFeatureDependencies): () -> IMyFeature {
        getDependenciesCallback = getDependencies
        return { init() }
    }

    private fun init(): IMyFeature {
        localComponentStorage = ComponentStorage(
            rootComponent = DaggerMyFeatureComponent.builder()
                // ...
                .build()
        )
        return componentStorage.rootComponent
    }
}
```

No thread synchronization (`@Volatile`, `synchronized`) — do not flag this as an issue in code review.
