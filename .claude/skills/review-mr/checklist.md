# MR Review Checklist

## General (both platforms)

- [ ] Logic matches Jira acceptance criteria
- [ ] Edge cases handled: empty state, error state, loading state
- [ ] No hardcoded strings / magic numbers
- [ ] No debug code left (print, log, TODO, FIXME without a ticket)
- [ ] No unnecessary scope creep — changes are minimal and targeted
- [ ] No new patterns introduced without justification (follow existing conventions)
- [ ] No unnecessary dependencies added
- [ ] Tests added or updated where applicable

## iOS (Swift / VIPER)

**VIPER structure:**
- [ ] Each VIPER layer has correct responsibility (View=display only, Interactor=business logic, Presenter=formatting, Router=navigation, Assembly=wiring)
- [ ] No business logic in View or Presenter
- [ ] Protocols defined correctly: View protocol + ModuleInput if needed
- [ ] Assembly wires all dependencies — no manual init outside assembly

**Memory & threading:**
- [ ] No retain cycles — closures capture `[weak self]` where needed
- [ ] Completion handlers stored weakly when necessary
- [ ] UI updates on main thread (`DispatchQueue.main` / `@MainActor`)
- [ ] No force unwraps (`!`) without justification

**Coding rules:**
- [ ] No `async/await` — project uses completion handlers
- [ ] API response models not used directly in business logic (mapped to domain models)
- [ ] No new third-party dependencies without discussion

**Testing:**
- [ ] Test method name: `test_methodName_condition_expectedResult`
- [ ] Arrange / Act / Assert structure with blank lines
- [ ] Mocks generated or follow existing mock patterns
- [ ] No `sleep` or real async in tests — synchronous and deterministic

## Android (Kotlin / MVP + Moxy + RxJava)

**MVP / Moxy:**
- [ ] Presenter contains business logic, not Fragment/Activity
- [ ] Contract file defines View interface + Presenter interface
- [ ] View state managed via `@StateStrategyType` annotations
- [ ] No direct View references stored in Presenter beyond Moxy injection

**Compose:**
- [ ] Composables are stateless — state hoisted to ViewModel/Presenter
- [ ] No business logic inside composables
- [ ] Proper state ownership (`remember`, `collectAsState` at correct level)
- [ ] Previews added for new composables
- [ ] Test tags added for interactive elements

**RxJava:**
- [ ] Subscriptions added to `CompositeDisposable` and disposed on detach
- [ ] Threading explicit: `subscribeOn` + `observeOn` where needed
- [ ] Errors handled — no silent swallowing
- [ ] No `blockingGet` / `blockingFirst` on main thread

**Dagger DI:**
- [ ] `MyFeatureDI.kt` file present for new features
- [ ] Module structure follows existing patterns
- [ ] No manual `new` for dependencies that should be injected

**Navigation (Cicerone):**
- [ ] Internal screens navigated via Router, not direct Fragment transactions
- [ ] External screens use correct contract

**General Kotlin:**
- [ ] No `!!` without justification
- [ ] SharedPreferences not accessed on main thread
- [ ] Profile/company/language context passed where required (not fetched globally)
