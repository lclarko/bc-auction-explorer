# Backlog

## Transport hardening

- Stream HTTP response bodies so `max_html_bytes` is enforced before a complete oversized body is buffered. Preserve redirect handling, retry behavior, response validation, and connection cleanup.
