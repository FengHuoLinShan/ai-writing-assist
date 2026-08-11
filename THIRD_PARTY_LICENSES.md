# Third-Party Licenses

This inventory covers direct production dependencies at the versions resolved
by the repository lockfiles on 2026-08-06. Transitive, build, test, and optional
dependencies remain recorded in `backend/uv.lock` and
`frontend-console/package-lock.json`; their package metadata and license files
are authoritative if this summary differs.

## Browser runtime

| Component | Locked version | License | Production license asset |
|---|---:|---|---|
| Leaflet | 1.9.4 | BSD-2-Clause | `/licenses/leaflet-BSD-2-Clause.txt` |
| Pinia | 4.0.2 | MIT | package metadata/lockfile |
| Vue | 3.5.40 | MIT | package metadata/lockfile |

The Leaflet asset is copied byte-for-byte from `node_modules/leaflet/LICENSE`
during the locked Vite build. Leaflet JavaScript and CSS are served from the
application origin and loaded only when the map viewport is entered.

## Backend runtime

| Component | Locked version | Declared license |
|---|---:|---|
| Authlib | 1.7.2 | BSD-3-Clause |
| Beautiful Soup | 4.15.0 | MIT |
| chardet | 7.4.3 | 0BSD |
| EbookLib | 0.20 | AGPL-3.0-or-later |
| FastAPI | 0.141.1 | MIT |
| email-validator | 2.3.0 | Unlicense |
| Uvicorn | 0.52.1 | BSD-3-Clause |
| SQLAlchemy | 2.0.51 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| psycopg2-binary | 2.9.12 | LGPL with exceptions |
| Alembic | 1.18.5 | MIT |
| pgvector | 0.5.0 | MIT |
| Pydantic | 2.13.4 | MIT |
| pydantic-settings | 2.14.2 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| OpenAI Python | 2.52.0 | Apache-2.0 |
| HTTPX | 0.28.1 | BSD-3-Clause |
| cryptography | 50.0.0 | Apache-2.0 OR BSD-3-Clause |
| tiktoken | 0.13.0 | MIT |
| RapidFuzz | 3.14.5 | MIT |
| ItsDangerous | 2.2.0 | BSD |
| joserfc | 1.7.4 | BSD-3-Clause |
| pypinyin | 0.55.0 | MIT |

EbookLib's declared AGPL-3.0-or-later terms require a separate legal and
distribution review before claiming closed-source commercial compatibility.
This inventory is engineering evidence, not legal advice, and does not alter
the project's own MIT license or any third-party terms.
