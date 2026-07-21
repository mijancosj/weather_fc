# PostgreSQL setup (no Docker)

The backend persists all normalized price data in Postgres. Locally, that
means a native PostgreSQL install — no container runtime needed. In the
cloud, `BACKEND_DATABASE_URL` just points at a managed Postgres instance
(RDS, Cloud SQL, Azure Database for PostgreSQL, Neon, Supabase, ...) instead;
nothing in the backend code changes.

## Windows (native install, done for this machine)

Installed via `winget`:

```powershell
winget install --id PostgreSQL.PostgreSQL.17 -e --silent `
  --accept-package-agreements --accept-source-agreements `
  --override "--mode unattended --unattendedmodeui minimal --superpassword postgres --servicename postgresql-x64-17 --serverport 5432 --enable-components server,commandlinetools"
```

This installs:
- The PostgreSQL 17 server, running as a Windows service (`postgresql-x64-17`), listening on port 5432.
- Command-line tools (`psql`, `createdb`, etc.) — typically under
  `C:\Program Files\PostgreSQL\17\bin`, added to `PATH`.
- Superuser `postgres` with password `postgres`.

**This is a local dev convenience password.** If this instance is ever
reachable from outside your machine, or holds anything beyond local dev
data, change it:

```powershell
psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'something-stronger';"
```

## Create the application database + role

Don't point the app at the `postgres` superuser — create a dedicated
database and a role scoped to it (`scripts/db-setup.ps1` does this):

```powershell
.\scripts\db-setup.ps1
```

This creates:
- Role `price_discovery` / password `price_discovery` (also a local dev
  default — change it and update `BACKEND_DATABASE_URL` together).
- Database `price_discovery`, owned by that role.

Matches the default already checked into `backend/.env`:

```
BACKEND_DATABASE_URL=postgresql+asyncpg://price_discovery:price_discovery@localhost:5432/price_discovery
```

## Apply the schema

Once the database exists:

```powershell
cd backend
uv run alembic upgrade head
```

This runs `migrations/versions/0001_create_prices_table.py`, which creates
the `prices` table `backend/src/backend/db/models.py` maps to. Future schema
changes are new Alembic revisions (`uv run alembic revision -m "..."`) —
never hand-edit the schema out of band.

## Verify

```powershell
psql -U price_discovery -d price_discovery -h localhost -c "\dt"
```

Should list the `prices` and `indicator_observations` tables (and Alembic's
own `alembic_version` table) after migrations have been applied.

## Browsing tables and data (pgAdmin 4)

Installed via `winget install --id PostgreSQL.pgAdmin -e`. First launch opens
in your browser and asks you to set a master password (for pgAdmin itself,
not Postgres). Then add a server connection:

1. Right-click **Servers → Register → Server...**
2. **General** tab: any name, e.g. `weather_fc local`
3. **Connection** tab:
   - Host: `localhost`
   - Port: `5432`
   - Maintenance database: `price_discovery`
   - Username: `price_discovery`
   - Password: `price_discovery` (check "Save password")

Once connected: **Servers → weather_fc local → Databases → price_discovery →
Schemas → public → Tables** lists `prices` and `indicator_observations` —
right-click a table → **View/Edit Data → All Rows** to browse it, or use the
**Query Tool** (toolbar icon) to run arbitrary SQL.

### Quicker, no GUI: `psql` cheat-sheet

```powershell
psql -U price_discovery -d price_discovery -h localhost

\dt                                   -- list tables
\d prices                             -- describe a table's columns
SELECT * FROM prices ORDER BY timestamp DESC LIMIT 20;
SELECT source, indicator_id, COUNT(*), MIN(timestamp), MAX(timestamp)
  FROM indicator_observations GROUP BY source, indicator_id;
\q                                     -- quit
```

## Moving to the cloud later

Nothing here is Windows- or local-install-specific at the application layer
— swap `BACKEND_DATABASE_URL` for the managed instance's connection string
(with `+asyncpg` kept in the scheme) and run `alembic upgrade head` against
it once. The `postgres`/`price_discovery` passwords above are dev-only;
production credentials should come from your cloud provider's secrets
manager, not a committed `.env` file.
