# Chess Coach frontend

SvelteKit and TypeScript frontend. Shared architecture, Tailwind styling rules,
and completion checks live in [AGENTS.md](../AGENTS.md).

## Setup

From this directory:

```sh
pnpm install
pnpm test:setup
```

The setup command installs Chromium for component and end-to-end tests. Repeat it
when the Playwright browser version changes. Test execution does not download
browsers or install dependencies.

## Development

```sh
pnpm dev
```

## Tests and build

- `pnpm lint`: Prettier and ESLint checks.
- `pnpm check`: Svelte and TypeScript checks.
- `pnpm test`: run unit and browser component tests once.
- `pnpm test:unit`: run tests in watch mode.
- `pnpm test:e2e`: run Playwright end-to-end tests (builds and previews the app).
- `pnpm build`: production build.
- `pnpm preview`: preview the production build.

Style application markup with Tailwind classes. `src/routes/layout.css` contains
only Tailwind setup. The current app is a scaffold; production serving will need
a deliberate adapter choice when that feature is implemented.
