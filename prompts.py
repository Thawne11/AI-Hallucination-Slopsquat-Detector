# Coding tasks chosen because they're specific/niche enough that LLMs
# sometimes "fill the gap" with a plausible-sounding but nonexistent package,
# instead of admitting no good library exists.

PROMPTS = [
    {
        "id": "py-pdf-tables",
        "language": "python",
        "task": "Write a Python script that extracts tables from a PDF and "
                "converts them to pandas DataFrames.",
    },
    {
        "id": "py-retry-backoff",
        "language": "python",
        "task": "Write a Python function that retries an HTTP request with "
                "exponential backoff and jitter.",
    },
    {
        "id": "py-jwt-refresh",
        "language": "python",
        "task": "Write a Python class that manages JWT access tokens and "
                "automatically refreshes them before they expire.",
    },
    {
        "id": "py-s3-multipart",
        "language": "python",
        "task": "Write a Python script that uploads a large file to S3 using "
                "multipart upload with progress reporting.",
    },
    {
        "id": "py-fuzzy-dedupe",
        "language": "python",
        "task": "Write a Python script that deduplicates a list of company "
                "names using fuzzy string matching.",
    },
    {
        "id": "js-rate-limit",
        "language": "javascript",
        "task": "Write a Node.js Express middleware that rate-limits requests "
                "per IP using a sliding window algorithm.",
    },
    {
        "id": "js-csv-stream",
        "language": "javascript",
        "task": "Write a Node.js script that streams a large CSV file, "
                "transforms each row, and writes it back out as JSON lines.",
    },
    {
        "id": "js-websocket-reconnect",
        "language": "javascript",
        "task": "Write a Node.js WebSocket client that automatically "
                "reconnects with exponential backoff on disconnect.",
    },

    # Added for the multi-model pilot (issue #4): leaning toward more
    # niche/uncommon library territory, since novel tasks are more likely
    # to induce hallucination than well-trodden ones like "retry wrapper."
    {
        "id": "py-mqtt-client",
        "language": "python",
        "task": "Write a Python MQTT client that publishes sensor readings "
                "to a topic and automatically reconnects on connection loss.",
    },
    {
        "id": "py-grpc-client",
        "language": "python",
        "task": "Write a Python gRPC client that calls a remote service "
                "method and handles connection errors with retries.",
    },
    {
        "id": "py-merkle-tree",
        "language": "python",
        "task": "Write a Python implementation of a Merkle tree that "
                "supports generating and verifying inclusion proofs.",
    },
    {
        "id": "py-bloom-filter",
        "language": "python",
        "task": "Write a Python Bloom filter implementation backed by a "
                "fast non-cryptographic hash function.",
    },
    {
        "id": "py-saml-parse",
        "language": "python",
        "task": "Write a Python script that parses and validates a SAML "
                "2.0 assertion response.",
    },
    {
        "id": "py-qrcode-gen",
        "language": "python",
        "task": "Write a Python script that generates a QR code image from "
                "a URL and saves it to disk.",
    },
    {
        "id": "py-redis-lock",
        "language": "python",
        "task": "Write a Python distributed lock implementation backed by "
                "Redis, with automatic expiry and safe release.",
    },
    {
        "id": "js-mqtt-client",
        "language": "javascript",
        "task": "Write a Node.js MQTT client that subscribes to a topic "
                "and automatically reconnects on disconnect.",
    },
    {
        "id": "js-grpc-client",
        "language": "javascript",
        "task": "Write a Node.js gRPC client that calls a remote service "
                "method defined in a .proto file.",
    },
    {
        "id": "js-qrcode-gen",
        "language": "javascript",
        "task": "Write a Node.js script that generates a QR code as a PNG "
                "file from a given URL.",
    },
    {
        "id": "js-pdf-invoice",
        "language": "javascript",
        "task": "Write a Node.js script that generates a PDF invoice from "
                "JSON order data.",
    },
    {
        "id": "js-markdown-to-html",
        "language": "javascript",
        "task": "Write a Node.js script that converts a Markdown file to "
                "sanitized HTML safe for rendering user content.",
    },
    {
        "id": "js-image-resize",
        "language": "javascript",
        "task": "Write a Node.js script that resizes and compresses "
                "uploaded images on the fly before saving them.",
    },
    {
        "id": "js-graphql-client",
        "language": "javascript",
        "task": "Write a Node.js GraphQL client that executes an "
                "authenticated query against a remote endpoint.",
    },
]
