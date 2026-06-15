# Using buzzsearch from Hermes Agent

buzzsearch is a first-class skill in [Hermes Agent](https://hermes-agent.nousresearch.com). When running inside a Hermes session, it gains additional capabilities:

## Additional Features Inside Hermes

### X/Twitter Cookie Login
The `--x-login` flag requires Hermes browser tools (`hermes_tools`). Inside a Hermes session:

```bash
# In a terminal tool command:
python3 /path/to/buzzsearch.py --x-login
```

The script imports `browser_navigate`, `browser_type`, `browser_press`, etc. from `hermes_tools` via a guarded import:

```python
try:
    from hermes_tools import (
        browser_navigate,
        browser_type,
        browser_press,
        browser_snapshot,
        browser_console,
    )
    HERMES_TOOLS_AVAILABLE = True
except ImportError:
    HERMES_TOOLS_AVAILABLE = False
```

### Browser-Based X Search (fallback)
When the cookie API returns 403, buzzsearch falls back to driving the Camofox browser via `browser_navigate` and `browser_console` to navigate to X search and extract tweet data from the DOM.

## Standalone Mode

When run outside Hermes (standalone `python3 buzzsearch.py`), the `hermes_tools` import fails gracefully and:
- `--x-login` is unavailable (prints an error message)
- X search tries xAI API or returns empty
- All other sources work identically

## Example Hermes Agent Usage

```
# User prompt to an agent:
buzzsearch latest on AI regulation

# The agent runs:
python3 buzzsearch.py "AI regulation" --depth default
```
