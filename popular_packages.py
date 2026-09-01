"""
Reference lists of widely-used package names, used only as typosquat anchors.

A name one or two edits away from something enormously popular is the classic
typosquat shape (`reqeusts`, `loadsh`, `expres`). These lists are the "what is
it pretending to be?" side of that check.

Deliberately embedded rather than fetched: the check stays deterministic and
testable offline, and a network hiccup cannot silently disable a risk signal.
The lists are approximate, not authoritative -- they cover the most-installed
packages, which is all a proximity check needs. Missing an anchor costs recall
on one signal, never correctness of the rest.
"""

POPULAR_PYPI = {
    "boto3", "botocore", "urllib3", "requests", "setuptools", "certifi",
    "charset-normalizer", "idna", "typing-extensions", "python-dateutil",
    "six", "s3transfer", "packaging", "numpy", "pyyaml", "cryptography",
    "awscli", "pip", "attrs", "click", "jinja2", "markupsafe", "pandas",
    "protobuf", "rsa", "pyasn1", "jmespath", "wheel", "colorama",
    "importlib-metadata", "zipp", "googleapis-common-protos",
    "google-api-core", "cffi", "pycparser", "filelock", "platformdirs",
    "virtualenv", "distlib", "tomli", "exceptiongroup", "pluggy",
    "iniconfig", "pytest", "scipy", "matplotlib", "pillow", "sqlalchemy",
    "greenlet", "psycopg2-binary", "redis", "flask", "werkzeug",
    "itsdangerous", "django", "fastapi", "pydantic", "starlette", "uvicorn",
    "httpx", "httpcore", "h11", "anyio", "sniffio", "aiohttp", "yarl",
    "multidict", "frozenlist", "aiosignal", "grpcio", "google-auth",
    "cachetools", "oauthlib", "requests-oauthlib", "pyjwt", "docutils",
    "jsonschema", "more-itertools", "tqdm", "rich", "pygments", "typer",
    "scikit-learn", "joblib", "tenacity", "decorator", "wrapt", "lxml",
    "beautifulsoup4", "soupsieve", "openpyxl", "paramiko", "bcrypt",
    "pynacl", "gitpython", "celery", "kombu", "pytz", "tzdata",
    "transformers", "torch", "huggingface-hub", "tokenizers", "regex",
    "sentry-sdk", "structlog", "loguru", "python-dotenv", "pyarrow",
    "pdfplumber", "pypdf2", "anthropic", "openai",
}

POPULAR_NPM = {
    "lodash", "chalk", "react", "react-dom", "axios", "express", "tslib",
    "debug", "commander", "semver", "glob", "minimatch", "rimraf", "uuid",
    "moment", "classnames", "prop-types", "webpack", "babel-loader",
    "typescript", "eslint", "prettier", "jest", "mocha", "chai", "sinon",
    "dotenv", "cors", "body-parser", "cookie-parser", "morgan", "helmet",
    "jsonwebtoken", "bcrypt", "bcryptjs", "mongoose", "mongodb", "pg",
    "mysql2", "sequelize", "knex", "redis", "ioredis", "socket.io", "ws",
    "node-fetch", "cross-fetch", "form-data", "qs", "query-string", "yargs",
    "inquirer", "ora", "boxen", "nodemon", "concurrently", "husky",
    "lint-staged", "rollup", "vite", "esbuild", "postcss", "autoprefixer",
    "tailwindcss", "sass", "less", "styled-components", "next", "nuxt",
    "vue", "svelte", "rxjs", "redux", "react-redux", "zustand", "immer",
    "formik", "yup", "zod", "joi", "ajv", "date-fns", "dayjs", "luxon",
    "nanoid", "slugify", "marked", "highlight.js", "dompurify", "cheerio",
    "puppeteer", "playwright", "sharp", "multer", "aws-sdk", "firebase",
    "stripe", "twilio", "nodemailer", "winston", "pino", "request",
}

POPULAR_BY_ECOSYSTEM = {
    "python": POPULAR_PYPI,
    "javascript": POPULAR_NPM,
}
