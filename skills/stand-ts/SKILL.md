---
name: stand-ts
description: TypeScript and JavaScript standards. Use when writing TS/JS code. Prefer bun over npm for package management.
---

# TypeScript / JavaScript Standards

Standards for TypeScript and JavaScript code.

## Package Manager

- Prefer `bun` over `npm`
- Use `bun install` instead of `npm install`
- Use `bun run` instead of `npm run`
- Use `bunx` instead of `npx`

## Commands

```bash
# Install dependencies
bun install

# Run scripts
bun run build
bun run test
bun run dev

# Execute packages
bunx <package>
```
