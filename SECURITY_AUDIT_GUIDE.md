# Security Audit Guide for buzzsearch

This guide shows how to run security audits on the buzzsearch repository using:
1. Snyk (for vulnerability scanning)
2. Socket.dev (for supply chain security)
3. Gen Agent Trust Hub (Hermes Agent's built-in security features)

## Prerequisites

- The buzzsearch repository cloned locally
- API tokens configured in `~/.hermes/.env`:
  - `SNYK_API_TOKEN=your_snyk_token_here`
  - `SOCKETDEV_API_TOKEN_VALUE=your_socket_token_here`

## Step 1: Extract Tokens

First, extract the tokens from your Hermes environment:

```bash
# Extract SNYK token
SNYK_TOKEN=*** '^SNYK_API_TOKEN=*** /root/.hermes/.env | cut -d'=' -f2-)

# Extract SOCKET token
SOCKET_TOKEN=*** '^SOCKETDEV_API_TOKEN_VALUE=*** /root/.hermes/.env | cut -d'=' -f2-)

echo "SNYK Token: ${SNYK_TOKEN:0:10}... (length: ${#SNYK_TOKEN})"
echo "SOCKET Token: ${SOCKET_TOKEN:0:10}... (length: ${#SOCKET_TOKEN})"
```

## Step 2: Run Snyk Security Audit

Snyk scans for vulnerabilities in code and dependencies.

```bash
# Set up environment
export PATH="/root/.hermes/node/bin:$PATH"
cd /root/buzzsearch

# Note: Snyk CLI authentication is interactive and requires browser login
# First-time setup: run `snyk auth` and follow the browser prompts
# After auth, or if already authenticated, run the scan:

export SNYK_TOKEN=*** SNYK_API_TOKEN=*** snyk code test --severity-threshold=medium
```

### Expected Snyk Output
Based on our scan, you should see findings like:
```
✗ [MEDIUM] Server-Side Request Forgery (SSRF)
   Finding ID: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
   Path: buzzsearch.py, line XXXX
   Info: Unsanitized input from a command line argument flows into urllib.request.urlopen...
```

## Step 3: Run Socket.dev Supply Chain Audit

Socket.dev scans for supply chain risks in dependencies.

```bash
# Set up environment
export PATH="/root/.hermes/node/bin:$PATH"
cd /root/buzzsearch

# Socket CLI requires SOCKET_CLI_API_TOKEN environment variable
export SOCKET_CLI_API_TOKEN=*** npx @socketsecurity/cli scan create --json
```

### Socket CLI Authentication Notes
- If prompted for credentials in a non-interactive shell, use:
  `export SOCKET_CLI_API_TOKEN=your_token_here` before running commands
- To avoid interactive prompts, you may need to run `socket login` first in an interactive shell
- The scan will ask if you want to use the current directory as the target - answer "Yes" or use `--yes` flag if available

## Step 4: Gen Agent Trust Hub (Hermes Agent Security)

The Hermes Agent includes built-in security features that provide continuous security monitoring:

### Built-in Security Features
1. **Tool Usage Monitoring**: All tool executions are logged and monitored
2. **File Access Controls**: Restricts access to sensitive paths
3. **Network Call Validation**: Validates outgoing requests against allowlists
4. **Session Isolation**: Each skill run occurs in an isolated environment
5. **Credential Protection**: API keys are masked in logs and outputs

### To Leverage Trust Hub Features:
- Run buzzsearch through the Hermes Agent skill system:
  ```
  # In a Hermes chat session:
  buzzsearch your research topic here
  ```
- The Agent automatically applies security policies and monitoring
- Review security logs via `hermes logs` or the Agent dashboard
- Skill execution is sandboxed to prevent unauthorized access

## Interpreting Results

### Snyk Findings
Focus on:
- **High/Medium severity issues**: Address these first
- **SSRF vulnerabilities**: Ensure input validation for URL parameters
- **Dependency issues**: Update any vulnerable dependencies (though buzzsearch has minimal deps)

### Socket.dev Findings
Check for:
- **Supply chain risks**: Malicious or compromised dependencies
- **License conflicts**: Incompatible licenses in dependencies
- **Quality warnings**: Poorly maintained packages

### Trust Hub Monitoring
Review:
- **Tool call logs**: For unexpected or unauthorized tool usage
- **File access patterns**: For attempts to read sensitive files
- **Network requests**: For unexpected outgoing connections

## Remediation Recommendations

Based on the SSRF findings in buzzsearch.py:
1. **Input Validation**: Sanitize/validate the `topic` parameter before using it in URLs
2. **Allowlist Approach**: Restrict URL construction to known-safe domains
3. **URL Encoding**: Properly encode user input when building query parameters
4. **Consider Allowlists**: For web search, consider restricting to known search APIs

## Running Audits in CI/CD

To integrate these scans into your CI pipeline:

```bash
# In your CI configuration:
export PATH="/root/.hermes/node/bin:$PATH"
cd /path/to/buzzsearch

# Extract tokens from secure secret store
export SNYK_TOKEN=*** SNYK_API_TOKEN=*** 
export SOCKET_CLI_API_TOKEN=*** 

# Run scans
snyk code test --severity-threshold=medium
npx @socketsecurity/cli scan create --format=json --output=socket-results.json
```

## Contact

For questions about securing your Hermes Agent deployments or buzzsearch usage,
refer to the Hermes Agent documentation or contact your security team.
