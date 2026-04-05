# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | ✅        |

QARA is currently pre-1.0. Security fixes are applied to the latest `main` branch.

---

## Reporting a Vulnerability

If you discover a security vulnerability in QARA, **please do not open a public GitHub issue**.

Instead, report it privately by emailing the maintainers at:

**arulprasath36@gmail.com**

Or use GitHub's [private security advisory](https://github.com/your-org/qara/security/advisories/new) feature if available.

You can expect:
- **Acknowledgment** within 48 hours
- **Assessment and response** within 7 business days
- **Coordinated disclosure** once a fix is available

---

## Scope

QARA is a local-only CLI tool that reads files from the local filesystem. It does not connect to the internet, cloud services, or external APIs in v1.

The primary attack surface is:
- **Malicious HTML/JSON report files**: QARA parses HTML and JSON from report files. Carefully crafted malicious files could potentially exploit parsing vulnerabilities in BeautifulSoup4, lxml, or the Python standard library's JSON parser.

We take care to:
- Never execute content parsed from reports
- Sanitize extracted strings before writing outputs
- Not evaluate or exec any script content found in report files

---

## Out of Scope

- Social engineering
- Vulnerabilities introduced by downstream dependencies (report them to those projects)
- Vulnerabilities in the user's own report-generating tools

---

## Acknowledgments

We appreciate responsible disclosure and will credit reporters in the release notes unless you request anonymity.
