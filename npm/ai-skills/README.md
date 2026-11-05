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
validates every adapter when it registers, `execute.ts` turns plans into journal
ops confined to their declared roots, and `types.ts` is the contract.

Install state and recovery live in `lib/journal/` (ADR 0010).
`journal.ts` applies ops write-ahead: each op's `begin` record and preimage
(content-addressed under `pre/`) are flushed before it runs and `done` after,
and undo is computed from the log and the filesystem, never from memory. It also
holds the `O_EXCL` state lock. `receipts.ts` reads and atomically replaces the
per-scope receipt, the commit point. `recover.ts` opens state sessions (lock,
then recovery, then the installed view), commits receipts and archives journals
as generations. `rollback.ts` plans the compensating ops for `sk rollback`.
`test/journal-crash.test.ts` kills a child after and inside every op of a
multi-adapter install and update and checks the next command converges.
`test/adapters-host-literals.test.ts` fails when code outside `lib/adapters/`
names a host or branches on one.

The legacy golden fixture was captured from commit
`fb3468e613584c2a7ec2aa337ffcda70a196ef63` before conversion, using the scenario in
`scripts/golden-scenario.ts`, and re-captured by #579 and #580. #579 removed the
behavior the original capture recorded: managed installs no longer hand off to
the skills CLI, so the scenario now explodes a local fixture catalog and adds an
explicit `--unmanaged` step, which runs the CLI and writes no lock. #580 moved
install state from `ai-skills-lock.json` into the machine-local receipt; the
scenario records the receipt's generation and plugin records (identical to the
records the lock held) instead of the raw state files.
The scenario exercises command dispatch against fixture homes with injected
upstream execution and a fixed clock. It compares stdout, stderr, status,
invocation arguments, committed plugin records, and written file bytes. Only the temporary
home and catalog prefixes are normalized. The test runs the scenario against both
source and emitted modules in separate processes. Outside a deliberate,
documented behavior change like #579 or #580, never regenerate the fixture to make a
failed comparison pass.
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
