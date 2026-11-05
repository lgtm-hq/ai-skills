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

Host-specific code lives only in `lib/adapters/` (ADR 0010). Each host directory
(`claude-code/`, `copilot/`, `cursor/`, `codex/`) declares its host table entry
(skill directory, CLI binary, label, native route) and its adapter;
`shared/skill-explode.ts` is the multi-host explode engine. `registry.ts`
validates every adapter when it registers, `execute.ts` applies a plan's ops with
in-memory undo inside the plan's declared roots, and `types.ts` is the contract.
`test/adapters-host-literals.test.ts` fails when code outside `lib/adapters/`
names a host or branches on one.

The legacy golden fixture was captured from commit
`fb3468e613584c2a7ec2aa337ffcda70a196ef63` before conversion, using the scenario in
`scripts/golden-scenario.ts`. It was re-captured once, deliberately, for #579:
managed installs now explode a local catalog, and the skills CLI runs only for the
explicit `--unmanaged` handoff, which writes no lock. It exercises the original
command dispatch against fixture homes with injected upstream execution and a
fixed clock. It compares
stdout, stderr, status, invocation arguments, lock JSON bytes, and written file
bytes. Only the temporary home and catalog prefixes are normalized. The test runs the scenario
against both source and emitted modules in separate processes. The fixture must
not be regenerated from migrated code to make a failed comparison pass.
`test/fixtures/legacy-catalog/{bundles,vendors}.json` preserves the catalog inputs
from that same commit. The scenario uses the real catalog reader with those
paths, independent of current bundle membership, vendor pins, and bake output.

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
stdin, and forwarded SIGINT/SIGTERM/SIGHUP. POSIX tests also check payload deaths
from SIGPIPE, SIGUSR1, and SIGALRM: they produce nonzero statuses without activating
a debugger. This certifies the launcher contract only;
production Python payload packaging and delivery remain #386 work.
