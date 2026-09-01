# Unreleased

Changes merged since v2026.08.0. This section is renamed to the version heading when
the next release is cut.

## Upgrade notes

1. **Run `alembic upgrade head` on your *current* checkout before deploying this
   release**, then deploy, then run `alembic stamp --purge orm_baseline`
   (`--purge` is required — the squash drops the pre-cutover id from the
   revision map). This release squashes the Alembic history to a single
   baseline revision, so a database left behind head cannot be migrated
   afterwards — the revisions it still needs (including the one adding
   `AuditLog`) are no longer on the trail. Deploying first leaves Alembic
   unable to resolve your current revision. Full procedure:
   `docs/runbooks/2026-08-20-alembic-squash-cutover.md`.

---

# EyeNED Platform v2026.08.0

This release focuses on viewer persistence and enface overlays, a service-layer cutover with an audit log (groundwork for RBAC), and a rewrite of CFI model inference. Version numbers follow calendar versioning (`YYYY.MM.MICRO`).

## Highlights

- **Viewer bookmarks:** open viewers and B-scan indices persist in the URL (`v=`) and localStorage (#198).
- **Enface on registered images:** overlays follow GPU registration hops; photolocator hit testing covers raster, radial, and circular locators (#177, #194).
- **Server service layer:** FastAPI routes go through repositories and services; mutations write an append-only `AuditLog`. This is preparation for RBAC, not a permission-model change for operators (#171 and related PRs).
- **CFI inference:** `eorm run-cfi-models` replaces the previous CFI writers, with model versions, input specs, and more robust batching (#158).
- **CI:** client and server test/lint gates on `development` and `main`.

## Bug fixes

**Viewer**

- Large DICOM volumes and IR/OCT stretch (#196).
- Patient registration on task viewer (#144).
- CirclePhotoLocator crash (#157).
- Multiclass erode/dilate (#131).
- Copy public ID from browser and viewer thumbnails (#140, #143).

**ORM / server**

- PNG series path resolution (#191).
- CFI inference filtering, thumbnails, lock/deadlock replay (#158).
- Removed unused `mysql-connector-python` (#199).

### Upgrade notes

1. Run database migrations before starting the new server containers (`AuditLog` table).
2. Reinstall `eyened_orm` after pulling.
3. Use `eorm run-cfi-models` instead of the removed legacy CFI writers.
4. Do not depend on `mysql-connector-python`.

# EyeNED Platform v2026.07.0

Major release: OpenID Connect login, a renewed ORM importer, centralized thumbnail generation, unified `eorm` CLI targeting, registration model versioning, major viewer and segmentation improvements, ETDRS/form-schema tooling, and refreshed deployment documentation.

## Highlights

- **OpenID Connect authentication** — optional SSO with secure ID-token validation, nonce/CSRF checks, optional automatic account creation, and a local Keycloak setup for development.
- **Renewed ORM importer** — plans changes before applying them, supports CSV input, JSON audit/undo files, idempotent re-runs, and clearer matching of patient/study/series/image records. Clearer errors when required parent records cannot be resolved.
- **Unified `eorm` CLI targeting** — shared `--path`, `--project`, `--patient`, `--exclude`, and `--modality` flags across inference and maintenance commands (`run-models`, `run-segmentation`, `run-registration`, `run-etdrs-model`, `update-thumbnails`, `update-hashes`).
- **Registration model versioning** — each package version gets its own `Model` row; patient attributes preserve provenance per model version; viewer crosshair linking works across registration graph versions.
- **Centralized thumbnail generation** — use `eorm update-thumbnails`, importer `PostImport`, or async API jobs backed by an RQ worker.
- **Segmentation and measurement improvements** — unified creation flows, region tools, feature pipette support, multiclass/multilabel opacity controls, B-scan link scrolling, probability-mask area calculation fixes, and clearer overlay rendering.
- **ETDRS and form schemas** — builtin viewer FormSchemas can be seeded with `eorm seed-form-schemas`; new ETDRS panel and Form Schema documentation.
- **Viewer UX** — embeddable browser widget in the viewer and task UI, global help panel, per-panel help overlays, browser overlay fixes, and smoother task/search performance.
- **Database setup** — `eorm initialize-database` now stamps the current Alembic revision; fresh installs should also run `eorm seed-form-schemas`.
- **Deployment and developer setup** — updated Docker, database, Redis/RQ worker, Keycloak, and storage docs; database dumps split into the `database/` stack.

## Bug fixes

- Segmentations now load when adding images dynamically to the viewer.
- Browser overlay correctly shows loaded images.
- ETDRS overlay renders correctly on enface OCT images.
- pyjwt dependency bump fixes an import error with `AllowedRSAKeys`.

## Upgrade notes

1. **Run database migrations** before starting the new server containers.
2. **Seed builtin form schemas** on new deployments: `eorm seed-form-schemas` (or `eorm initialize-database --seed-form-schemas`).
3. **Review authentication settings** before deployment. Password login remains enabled by default; OIDC is opt-in via `EYENED_API_AUTH_OIDC_ENABLED=true`.
4. **Ensure an RQ worker** listens to the `default` queue if you use async thumbnail jobs.
5. **Reinstall `eyened_orm`** after pulling this release so ORM-owned dependencies (including `zarr`) are current.
6. **Patient attributes API change:** `GET /patients/{id}` now returns each attribute as a list of `{ value, model }` entries so provenance per model version is preserved.

## Documentation

- [Release notes](https://eyened.github.io/eyened-platform/release_notes/)
- [Getting started](https://eyened.github.io/eyened-platform/getting_started/)
- [Authentication](https://eyened.github.io/eyened-platform/guides/authentication/)
- [Importing data](https://eyened.github.io/eyened-platform/importing_data/)
- [ETDRS panel](https://eyened.github.io/eyened-platform/client/etdrs_panel/)
- [Form schemas](https://eyened.github.io/eyened-platform/orm/form_schemas/)
