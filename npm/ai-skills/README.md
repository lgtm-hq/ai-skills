# Gateway development

The gateway is strict TypeScript. Run `bun install --frozen-lockfile`,
`bunx tsc --noEmit`, `bun test --coverage`, and `bun run build` in this directory.
Both npm bins execute `dist/bin/skill.js` with Node. `build:launcher` builds the
same emitted launcher. No install script or runtime download is required.

`scripts/ci/npm/check_ai_skills_package.sh` is the CI gate. It acquires and checks
vendor bake data through the existing Python generator before running the offline
unit suite, then builds, exercises the launcher fixture, and checks an actual
packed archive. Generated vendor scripts are upstream assets, not authored gateway
JavaScript. The source guard checks tracked and new authored package files;
historical research archives outside this package remain intact.

The legacy golden fixture was captured from commit
`fb3468e613584c2a7ec2aa337ffcda70a196ef63` before conversion, using the scenario in
`scripts/golden-scenario.ts`. It exercises the original command dispatch against
fixture homes with injected upstream execution and a fixed clock. It compares
stdout, stderr, status, invocation arguments, lock JSON bytes, and written file
bytes. Only the temporary home prefix is normalized. The test runs the scenario
against both source and emitted modules in separate processes. The fixture must
not be regenerated from migrated code to make a failed comparison pass.

ADR 0008 assigns future engine semantics to Python. If `data/runtime/` exists, the
launcher selects a supported target and invokes its local interpreter with
`engine/__main__.py`. `AI_SKILLS_RUNTIME_ROOT` supplies an alternate payload root
for fixtures. Targets are `linux-x64`, `linux-arm64`, `darwin-x64`, `darwin-arm64`,
and `windows-x64`. Unix interpreters are `python/bin/python3`; Windows uses
`python/python.exe`. Arguments, inherited streams, signals, and status pass
through directly. An explicitly selected missing/incomplete payload fails closed.
Until #386 ships production bundles using #567, packages without a runtime retain
the existing gateway commands.

`bun scripts/launcher-smoke.ts` stages a test interpreter and fixture entry point,
then launches source and emitted code from an empty cwd with an empty PATH. It
checks version/list output, literal arguments, stderr, status, child termination,
and forwarded SIGINT/SIGTERM/SIGHUP. This certifies the launcher contract only;
production Python payload packaging and delivery remain #386 work.
