# UI Refactor Brief

## Target Stack

This brief is specifically for a frontend rewrite using:

- Vite
- React
- TypeScript
- TSX component files

Do not treat this as a generic frontend rewrite brief. The intended outcome is a Vite-powered React application written in TypeScript with TSX-based components.

## Objective

Rebuild the frontend UI from scratch in Vite + React + TypeScript while preserving the product purpose and core behavior of the current application.

This is a UI overhaul, not a product redesign. The new frontend should feel substantially cleaner, more consistent, and easier to extend, but it must continue to serve the same purpose:

- authenticate a user
- create a download task from a magnet or direct link
- monitor live task progress
- select files for tasks in select mode
- cancel or delete tasks
- browse and download completed task files

## Product Purpose

This application is a private control panel for a backend that:

- accepts a magnet or supported link
- sends the job to the API/worker stack
- resolves files via AllDebrid
- downloads files through the worker
- stores output under a task-specific folder
- exposes live task status and file progress

The UI is an operator dashboard for managing those tasks. It should feel like a focused internal tool, not a marketing site.

## Rewrite Intent

The current frontend works, but it is patched together and difficult to evolve cleanly.

Problems in the current UI:

- styling is inconsistent across pages
- large amounts of inline CSS and inline JavaScript
- the login page uses a different visual system from the rest of the app
- task rendering, status logic, selection behavior, and live updates are tightly mixed together
- there is no cohesive component system
- the experience feels utilitarian rather than deliberate

The replacement UI should fix those structural problems while keeping feature parity.

## Required Frontend Platform Decision

The rewrite should assume the legacy Flask/Jinja frontend will be replaced by a dedicated Vite application.

Requirements:

- use Vite as the frontend build tool
- use React for rendering
- use TypeScript throughout the app
- use `.tsx` for UI components and route-level views
- avoid plain `.jsx` unless there is a very narrow reason and it is explicitly approved
- keep frontend concerns separated from backend template rendering

Preferred outcome:

- the backend remains responsible for API and task processing
- the new Vite app becomes the primary UI surface

## Non-Negotiable Constraints

- Keep the same app purpose.
- Keep the same core user flows.
- Do not remove features that exist today unless they are explicitly deprecated.
- Prefer improving clarity, layout, state handling, and design consistency over inventing new product behavior.
- Preserve compatibility with the existing backend API unless a backend change is explicitly approved.
- Build toward maintainability and component reuse.
- Build specifically for Vite + React + TypeScript, not a server-rendered template system.

## Current Frontend Scope

The current UI includes these primary screens and flows.

### 1. Login

Purpose:

- authenticate a frontend user through the existing login form

Current behavior:

- username and password form
- posts to `/login`
- redirects into the app on success

### 2. Home / Create Task

Purpose:

- create a new task from a magnet or direct link

Current behavior:

- shows backend health indicator
- input for source magnet/link
- mode selection: `auto` or `select`
- optional label support exists in backend flow and should remain supported in UI
- submits to `/tasks/new`
- redirects to task detail after creation

### 3. Task Detail

Purpose:

- show current task status and files
- allow selection in `select` mode
- allow destructive actions
- reflect live backend progress

Current behavior:

- shows task metadata such as status, label, infohash, and mode
- renders file rows with size, state, and local path when available
- in `select` mode, allows checkbox selection of files and submit of selected file IDs
- supports select all and clear all controls
- supports cancel task
- supports delete and purge task
- links to folder view
- receives live updates from server-sent events

### 4. Folder / File Browser

Purpose:

- browse the stored task output
- download individual files or a compressed archive

Current behavior:

- list files for a task
- download an individual file
- download all as `.tar.gz`
- access `links.txt` when present

## Core Feature Parity Requirements

The new UI must preserve all of the following capabilities.

### Authentication

- login form
- logged-in app shell
- logout access
- unauthorized users should be redirected to login

### Task Creation

- create task from magnet or supported direct link
- choose `auto` or `select` mode
- optionally include a label
- surface validation and backend errors clearly

### Task Monitoring

- show task status prominently
- show file list with size and state
- show per-file progress where available
- handle live updates cleanly
- handle reconnect or temporary stream failure gracefully

### Selection Workflow

- when a task is waiting for selection, render selectable files
- support individual file selection
- support bulk select and clear
- submit selected file IDs to backend

### Task Actions

- cancel task
- delete task
- purge files when deleting if supported by the current flow

### File Access

- browse files for a task
- download individual files
- download task archive
- expose links file when available

## Backend Contract To Preserve

Unless explicitly approved, the new frontend should continue using the current backend endpoints and semantics.

### Auth-Oriented Frontend Routes Today

- `/login`
- `/logout`
- `/`
- `/tasks/new`
- `/tasks/<task_id>`
- `/tasks/<task_id>/select`
- `/tasks/<task_id>/cancel`
- `/tasks/<task_id>/delete`
- folder and download routes for task output

### API Endpoints Exposed By Backend

- `POST /api/tasks`
- `GET /api/tasks/{taskId}`
- `POST /api/tasks/{taskId}/select`
- `POST /api/tasks/{taskId}/cancel`
- `DELETE /api/tasks/{taskId}`
- `GET /api/tasks/{taskId}/events`
- `GET /health`

The frontend may wrap these differently, but feature behavior must remain equivalent.

## UX Expectations For The New UI

The new interface should feel intentional and modern without becoming visually noisy.

Desired qualities:

- clear information hierarchy
- consistent typography, spacing, and controls
- better empty states, loading states, and error states
- responsive layout that works on desktop and mobile
- task status and actions should be obvious at a glance
- destructive actions should be visually distinct and safe
- live progress should be understandable without reading raw state strings only

The UI should look like a cohesive application shell with reusable components, not a set of unrelated pages.

## Visual Direction

The current app uses inconsistent styles. The new app should define one design system and apply it everywhere.

Required design foundations:

- shared color tokens
- shared spacing scale
- shared typography rules
- shared button, input, card, table, badge, and alert patterns
- consistent form validation treatment
- consistent empty/loading/error components

Suggested component primitives:

- app shell
- page header
- status badge
- health badge
- task summary card
- action bar
- file table
- file row
- progress bar
- alert banner or toast
- confirmation dialog
- empty state panel

## Suggested Information Architecture

The following structure is acceptable as long as feature parity is preserved.

### App Shell

- top navigation or header
- authenticated identity area
- logout action
- optional health indicator

### Pages

- login page
- create task page
- task detail page
- task files page

### Task Detail Layout

Suggested sections:

- task summary header
- task metadata
- primary actions
- selection controls when applicable
- live file table with status and progress
- system or error messages

## Technical Direction

This rewrite should be implemented as a Vite + React + TypeScript frontend.

### Required Technical Stack

- Vite
- React
- TypeScript
- TSX components
- CSS modules, scoped CSS, or a consistent global styling strategy

### Preferred Application Characteristics

- component-driven UI
- API-driven state
- reusable typed models for backend payloads
- minimal implicit global state
- explicit handling for loading, success, and error cases

### Frontend Project Expectations

The new frontend should have a structure similar to the following.

```text
frontend-v2/
	src/
		app/
		components/
		features/
		pages/
		lib/
		api/
		styles/
		types/
		main.tsx
```

The exact folder names can vary, but the architecture should still separate:

- app shell and bootstrapping
- page-level views
- reusable UI components
- API client code
- event-stream handling
- shared types
- styling tokens and primitives

Suggested approach:

- create a dedicated frontend app
- use reusable components instead of page-specific inline markup
- centralize API access in one layer
- centralize event stream handling in one layer
- use typed task and file models
- keep state transitions explicit and predictable

Do not fall back to template-first rendering unless explicitly requested.

## TypeScript Requirements

The rewrite should use TypeScript as a real design constraint, not just as file extensions.

Requirements:

- define explicit frontend types for task, file, storage, auth, and event payloads
- avoid broad `any` usage
- model task status and file state carefully
- use typed API helpers for request and response contracts
- keep types close to the domain model and reuse them across components

Suggested type areas:

- `Task`
- `TaskFile`
- `StorageInfo`
- `CreateTaskRequest`
- `CreateTaskResponse`
- `SelectRequest`
- SSE event payloads and normalized live state

## Routing Expectations

The Vite app should provide frontend routes that map cleanly to the current user flows.

Suggested route shape:

- `/login`
- `/`
- `/tasks/:taskId`
- `/tasks/:taskId/files`

If a client router is used, ensure it does not break backend integration assumptions.

## API Integration Expectations

The Vite app should treat the FastAPI service as the backend source of truth.

Requirements:

- centralize all fetch logic
- centralize auth/session behavior
- standardize error parsing and display
- keep API base URL configurable by environment
- support local development through Vite proxying or equivalent config

Suggested environment concerns:

- API base URL
- frontend port
- auth/session integration behavior
- development proxy behavior

## SSE Integration Expectations

The Vite app should handle task event streaming in a dedicated way rather than mixing it directly into page markup.

Recommended approach:

- create a typed event stream utility or hook
- normalize event payloads into current task state
- isolate reconnect behavior
- keep UI components focused on rendering, not transport details

Possible implementation shapes:

- `useTaskStream(taskId)` hook
- task-state reducer for merging snapshots and deltas
- stream status indicator for reconnecting or offline states

## Styling Direction For Vite UI

The new app should define one consistent design system at the frontend app level.

Requirements:

- define CSS variables or theme tokens centrally
- avoid page-level ad hoc styling as the default pattern
- avoid large inline style blocks inside TSX components
- establish reusable layout and form primitives early

Acceptable styling approaches:

- global CSS with strong conventions
- CSS modules
- another consistent styling system approved for the repo

Avoid:

- uncontrolled per-page styling drift
- mixing multiple unrelated visual systems
- recreating the same button, badge, and card styles in many files

## Suggested React Component Model

The rewrite should lean on composable TSX components.

Suggested component set:

- `AppShell`
- `TopBar`
- `HealthBadge`
- `LoginForm`
- `CreateTaskForm`
- `TaskHeader`
- `TaskStatusBadge`
- `TaskActions`
- `FileTable`
- `FileRow`
- `SelectionToolbar`
- `ProgressBar`
- `ErrorBanner`
- `EmptyState`
- `ConfirmDialog`

These names are suggestions, not strict requirements, but the architecture should be component-first.

## Live Update Requirements

The current task page depends on server-sent events. The new UI should treat live updates as a first-class feature.

Requirements:

- establish event stream for task detail
- merge incoming updates into visible task state
- keep task status, file states, and progress in sync
- avoid jittery or confusing rerenders
- show reconnect or stale connection state if the stream drops
- support final task states cleanly

## Error Handling Requirements

The new UI must improve error handling instead of hiding backend failures.

Must handle:

- invalid login
- failed task creation
- task lookup failure
- selection submission failure
- cancel failure
- delete failure
- event stream interruptions
- empty or missing file lists

Errors should be readable and actionable.

## Content And Tone

This is a utility application. Use clear, direct copy.

Prefer:

- concise labels
- short helper text
- explicit action names
- status copy that is easy to scan

Avoid:

- vague marketing language
- decorative copy that hides meaning
- overly playful language in destructive or error flows

## Acceptance Criteria

The rewrite is successful only if all of the following are true.

- a user can log in and out
- a user can create an auto task
- a user can create a select task
- a user can view task details without losing current behavior
- live task updates are visible and reliable
- file selection works correctly in select mode
- cancel works
- delete and purge flow works
- folder browsing and downloads work
- the UI is visually consistent across all pages
- the codebase is more maintainable than the current template-based implementation

## Migration Guidance For AI

When refactoring or rebuilding the UI, follow these rules.

### Preserve behavior first

- do not break working backend flows during visual overhaul
- treat current behavior as the baseline even if the implementation is messy
- keep route and API compatibility unless explicitly told otherwise

### Replace structure, not purpose

- replace the UI architecture freely
- improve layout, styling, and componentization aggressively
- do not change what the application is for
- target Vite + React + TypeScript as the replacement architecture

### Build in stages

- identify the current feature set before replacing screens
- rebuild one screen or flow at a time
- verify parity after each major slice

### Favor clarity over novelty

- prioritize readable UI and maintainable code
- do not introduce flashy interactions that distract from task management
- use motion sparingly and only where it improves comprehension

### Use Vite and TSX idiomatically

- use TSX components for interface composition
- keep components small and reusable
- isolate hooks, API utilities, and typed domain models
- do not reproduce server-template patterns inside React
- avoid building one oversized page component that mirrors the old template file

## Suggested Implementation Order

1. Create the Vite + React + TypeScript app foundation.
2. Define shared design tokens, shell layout, and base TSX primitives.
3. Rebuild authentication view.
4. Rebuild create-task screen.
5. Rebuild task detail screen with static typed data first.
6. Add live SSE integration.
7. Add selection flow.
8. Add cancel and delete flows.
9. Rebuild folder and download view.
10. Remove legacy frontend once parity is confirmed.

## Deliverables Expected From The Refactor

- a complete replacement UI with the same purpose and feature set
- consistent design system or component vocabulary
- improved code organization
- clear separation between presentation, state, and API integration
- no regression in task management workflows

## Prompt Seed For AI Agents

Use the following prompt as the starting instruction for any AI helping with the rewrite.

> Rebuild the frontend UI from scratch as a Vite + React + TypeScript application using TSX components while preserving the same product purpose and feature set. The current UI is functional but patched together. Create a cleaner, more cohesive, more maintainable frontend with consistent styling, reusable components, strong live task monitoring, and full parity for login, task creation, task detail, selection mode, cancel/delete actions, folder browsing, and downloads. Do not redesign the backend workflow. Preserve behavior and compatibility unless an explicit change is approved. Use typed API models, centralized fetch logic, dedicated SSE handling, and a component-first architecture.

## Final Standard

If a user familiar with the current app can do all the same work in the new UI, but faster and with less friction, the rewrite succeeded.