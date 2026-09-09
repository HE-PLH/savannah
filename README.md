# Clinic stock backend

Django REST browser-facing API for the clinic stock console. It authenticates against a local custom user table, reads catalogue data through DummyJSON, and persists confirmed stock corrections in MongoDB.

## Architecture

Django is the only service called by the browser. `inventory.User` extends Django's user model and stores users in `clinic_users`. A custom authentication backend performs case-insensitive lookup by email or username and verifies Django password hashes. Django sessions use an HTTP-only cookie and server-side session records, so logout revokes access immediately. Catalogue routes require an authenticated session. PyMongo provides a narrow repository around the `stock_overrides` collection.

Each override contains `clinic_id`, `product_id`, `stock`, and timestamps. The current deployment uses `clinic_id=default`; a multi-clinic rollout must derive this value from trusted identity claims and apply tenant authorization to every repository operation.

## Fetching and failure behavior

DummyJSON catalogue calls have a ten-second timeout. Network failures become a recoverable 503-style API error and upstream server failures are normalized. `DUMMYJSON_DELAY_MS` accepts 0–5000 to exercise slow paths. Product list requests accept up to 200 rows so the browser can virtualize the complete 194-item catalogue. The frontend requests a one-minute session at login so expiry can be exercised during testing; otherwise session lifetime defaults to `SESSION_COOKIE_AGE`. When it expires, the frontend returns to sign-in without replacing the current route.

A stock correction first receives a successful DummyJSON `PUT`, then upserts the durable MongoDB override. If persistence fails, the API returns an error rather than claiming the count was saved. List and detail reads merge available overrides. Every error uses `{ "error": { "code": string, "message": string } }`.

`POST /api/products/bulk-corrections` accepts one to 200 `{ "productId", "stock" }` entries. Each correction retains the same upstream-then-persistence ordering as the individual endpoint. Processing continues after an item fails, and the response reports per-item outcomes plus succeeded and failed totals.

## Decision log

### Local Django session authentication

**Decision:** import users into a custom Django table and authenticate with server-side sessions. **Rejected:** forwarding every login to DummyJSON and retaining upstream bearer tokens. **Why:** local sessions support immediate revocation, admin controls, email or username lookup, and operation when the external authentication endpoint is unavailable.

### Persist overrides after simulated updates

**Decision:** save successful corrections in MongoDB and merge them into subsequent reads. **Rejected:** treating the DummyJSON `PUT` response as durable state. **Why:** DummyJSON discards updates, so trusting it would make corrections disappear after a reload.

### Direct PyMongo repository

**Decision:** use PyMongo for the small override model. **Rejected:** an unofficial MongoDB Django ORM backend. **Why:** the required operation is a narrow upsert/read overlay, while an ORM adapter adds migration and Django-version compatibility risk.

### Pessimistic correction transaction

**Decision:** persist only after DummyJSON accepts the update and return failure if MongoDB cannot save it. **Rejected:** returning the simulated response before local persistence. **Why:** success must mean the count will survive a reload.

## DummyJSON limitations

DummyJSON contains generic retail products, so this API returns source content without inventing clinical descriptions. Updates are simulated and not retained; MongoDB provides durable overrides. DummyJSON does not combine category and search endpoints, so category results are fetched and then searched, sorted, and paginated by Django. Its users and passwords are public demonstration data. The seed command hashes each password immediately; these accounts must not be treated as production identities.

## Setup without Docker

Requirements: Python 3.12+, Node.js 22+ for commitlint, and MongoDB Community Server installed as a local service or a MongoDB Atlas connection.

1. Start MongoDB using the operating-system service manager, or create an Atlas database.
2. Copy `.env.example` to `.env`.
3. Set `MONGODB_URI` to the local or Atlas URI and set `MONGODB_DATABASE`.
4. Create and activate a virtual environment.
5. Run `python -m pip install -r requirements-dev.txt`.
6. Run `npm install` to install commitlint and the local Husky hook.
7. Run `python manage.py migrate`.
8. Run `python manage.py seed_dummyjson_users` to import all users from `https://dummyjson.com/users`.
9. Run `python manage.py runserver`.

The seed command is idempotent and updates profiles and password hashes by DummyJSON ID. Users can sign in with either their email or username and the password shown by DummyJSON. To create a local administrator, run `python manage.py createsuperuser` and open `/admin/`.

For Windows with the default MongoDB service, use the Services application or `Start-Service MongoDB` from an elevated PowerShell session. Docker is not required or configured by this repository.

## Quality commands

- `npm run format` and `npm run format:check` use Ruff.
- `npm run lint` uses Ruff's selected `E`, `F`, `I`, `B`, `UP`, `SIM`, and `DJ` rules.
- `npm run typecheck` uses strict mypy with Django and DRF plugins.
- `npm test` runs pytest.
- `npm run check` runs Django system checks.

Tests cover email and username login, invalid credentials, session logout, route protection, hashed user imports, normalized upstream failures, and stock persistence. Conventional Commits are enforced by commitlint through the committed Husky `commit-msg` hook.

## API

- `GET /api/auth/csrf`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/categories`
- `GET /api/products?q=&category=&sortBy=&order=&page=&limit=`
- `GET /api/products/:id`
- `PUT /api/products/:id` with `{ "stock": number }`

Set `DUMMYJSON_DELAY_MS=2000` to validate slow requests. Tests mock `/http/500` behavior through the upstream client. Production must use HTTPS, a strong secret, explicit trusted origins, HSTS, and secure cookies.
