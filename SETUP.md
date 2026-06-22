# YCPA Project Setup Guide

## Prerequisites — Install These First

| Tool | Version | Download |
|---|---|---|
| Python | 3.13.x | https://python.org |
| uv | latest | `pip install uv` |
| Node.js | 18+ | https://nodejs.org |
| PostgreSQL | 14+ | https://postgresql.org |

---

## 1. Database Setup

Open pgAdmin or psql and run:

```sql
CREATE DATABASE ifc;
```

---

## 2. Backend Setup

### 2a. Create `.env` file

Inside `ycpa-backend-feat-initial-setup/`, create a file named `.env`:

```env
ENVIRONMENT=local

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/ifc
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/ifc
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=YOUR_PASSWORD
POSTGRES_DB=ifc

# JWT (put any random strings here)
SECRET_KEY=local-secret-key-change-in-production
JWT_SECRET=local-jwt-secret-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AWS — leave as "local", not used locally
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=local
AWS_SECRET_ACCESS_KEY=local
COGNITO_USER_POOL_ID=local
COGNITO_APP_CLIENT_ID=local

# Third-party — leave as "local" if not using
GEMINI_API_KEY=local
RAZORPAY_KEY_ID=local
RAZORPAY_KEY_SECRET=local
```

> Replace `YOUR_PASSWORD` with your actual PostgreSQL password.

---

### 2b. Install dependencies

```bash
cd ycpa-backend-feat-initial-setup
pip install uv
uv sync
```

---

### 2c. Run database migrations

```bash
uv run alembic upgrade head
```

You should see a list of migration steps ending in `Done`.

---

### 2d. Seed RBAC roles (run once)

```bash
uv run python -m ycpa.seeders.seed_rbac
uv run python -m ycpa.seeders.seed_subscription_plans
```

This creates the 17 BIM roles (BIM Manager, Architect, etc.) and subscription plans.

---

### 2e. Start the backend

```bash
python run.py
```

Backend runs at → **http://localhost:8000**  
API docs → **http://localhost:8000/docs**

---

## 3. Frontend Setup

```bash
cd ycpa-frontend-feat-initial-setup
npm install
npm run dev
```

Frontend runs at → **http://localhost:5173**

---

## 4. First-Time Account Setup

### 4a. Create the admin account

Go to **http://localhost:5173/sign-up** and create:

| Field | Value |
|---|---|
| Full Name | Ashvanth (or any name) |
| Email | `ashh@gmail.com` |
| Password | your choice |

### 4b. Promote to super admin

After signing up, open psql or pgAdmin and run:

```sql
UPDATE users 
SET platform_role = 'super_admin' 
WHERE email = 'ashh@gmail.com';
```

### 4c. Create regular user accounts

Sign up normally for any other users (e.g. `user@test.com`).  
These stay as `customer` role — they can work inside projects but cannot create/delete workspaces.

---

## 5. How Roles Work

### Platform roles (global)

| Role | Who | Access |
|---|---|---|
| `super_admin` | `ashh@gmail.com` | Bypasses all permission checks |
| `customer` | Everyone else | Subject to workspace/project rules |

### Workspace roles (per workspace)

| Role | Can create projects | Can add members | Can delete workspace |
|---|---|---|---|
| `owner` | ✅ | ✅ | ✅ |
| `admin` | ✅ | ✅ | ❌ |
| `member` | ❌ | ❌ | ❌ |

### Project roles (BIM roles, per project)

Assigned when adding someone to a project:  
`BIM Manager`, `Architect`, `Site Engineer`, `MEP Engineer`, etc.

Each role controls which project modules they can access (CDE, IFC Viewer, BCF, QTO, etc.).

---

## 6. Adding Members to a Workspace

1. Log in as `ashh@gmail.com`
2. Go to PIM or AIM Workspaces
3. Click the 👥 button on any workspace row
4. Click **Add member**
5. Type the email of any user already registered in the database
6. Choose their role (`admin` or `member`)
7. Click **Add** — they're added instantly

---

## 7. Adding Members to a Project

1. Open a project → go to the **Team** tab
2. Click **Add member**
3. **From Workspace tab** → pick from existing workspace members
4. **Invite by Email tab** → type an email, choose a BIM role → this creates an in-app invitation
5. The invited user sees the invitation on their dashboard when they log in
6. They click **Accept** → they're added to the project with the assigned BIM role

---

## 8. Daily Development Workflow

Open two terminals:

**Terminal 1 — Backend:**
```bash
cd ycpa-backend-feat-initial-setup
python run.py
```

**Terminal 2 — Frontend:**
```bash
cd ycpa-frontend-feat-initial-setup
npm run dev
```

Then open **http://localhost:5173**

---

## 9. Useful Commands

```bash
# Create a new migration after changing a model
uv run alembic revision --autogenerate -m "description_here"
uv run alembic upgrade head

# Roll back last migration
uv run alembic downgrade -1

# Check current migration version
uv run alembic current

# Re-seed RBAC (safe to re-run)
uv run python -m ycpa.seeders.seed_rbac
```

---

## 10. Troubleshooting

| Error | Fix |
|---|---|
| `JWKS preload failed` | Already handled — backend continues in local mode |
| `422 Unprocessable Content` on signup | Check the request body matches `{ email, password, full_name }` |
| `405 Method Not Allowed` on project PATCH | Add the PATCH route to `pim.py` / `aim.py` endpoints |
| `403 Forbidden` when adding project members | Make sure `ashh@gmail.com` has `platform_role = 'super_admin'` in DB |
| `No account found` when inviting by email | The email must be registered (signed up) in your local DB first |
| Frontend blank page | Check `.env.local` has `VITE_YATZAR_IFC_API_URL=http://localhost:8000/api/v1` |
| Alembic error on `upgrade head` | Delete the DB, recreate it, run migrations fresh |

---

## 11. Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Async PostgreSQL URL (asyncpg driver) |
| `DATABASE_URL_SYNC` | ✅ | Sync PostgreSQL URL (psycopg2 driver) |
| `JWT_SECRET` | ✅ | Secret key for signing JWT tokens |
| `SECRET_KEY` | ✅ | App secret key |
| `JWT_ALGORITHM` | ✅ | Always `HS256` locally |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ✅ | Token lifetime in minutes (1440 = 24h) |
| `ENVIRONMENT` | ✅ | Set to `local` |
| `AWS_REGION` | ✅* | Set to `local` (not used locally) |
| `COGNITO_USER_POOL_ID` | ✅* | Set to `local` (not used locally) |
| `COGNITO_APP_CLIENT_ID` | ✅* | Set to `local` (not used locally) |
