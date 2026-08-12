# Third-Party Licenses

This inventory covers direct production dependencies at the versions resolved
by the repository lockfiles on 2026-08-12. Transitive, build, test, and optional
dependencies remain recorded in `backend/uv.lock` and
`frontend-console/package-lock.json`; their package metadata and license files
are authoritative if this summary differs.

## Browser runtime

| Component | Locked version | License | Production license asset |
|---|---:|---|---|
| Pinia | 4.0.2 | MIT | package metadata/lockfile |
| Vue | 3.5.40 | MIT | package metadata/lockfile |

## Backend runtime

| Component | Locked version | Declared license |
|---|---:|---|
| Authlib | 1.7.2 | BSD-3-Clause |
| Beautiful Soup | 4.15.0 | MIT |
| Boto3 | 1.43.69 | Apache-2.0 |
| chardet | 7.5.1 | 0BSD |
| EbookLib | 0.20 | AGPL-3.0-or-later |
| FastAPI | 0.141.1 | MIT |
| email-validator | 2.3.0 | Unlicense |
| Uvicorn | 0.52.1 | BSD-3-Clause |
| SQLAlchemy | 2.0.51 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| psycopg2-binary | 2.9.12 | LGPL with exceptions |
| Alembic | 1.19.0 | MIT |
| pgvector | 0.5.0 | MIT |
| Pydantic | 2.13.4 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| OpenAI Python | 2.53.0 | Apache-2.0 |
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
