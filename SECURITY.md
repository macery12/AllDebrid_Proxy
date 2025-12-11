# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please follow these steps:

### 1. Do NOT open a public issue

Security vulnerabilities should not be publicly disclosed until they have been addressed.

### 2. Report via GitHub Security Advisory

1. Go to the [Security tab](https://github.com/macery12/AllDebrid_Proxy/security/advisories)
2. Click "Report a vulnerability"
3. Provide detailed information about the vulnerability

### 3. What to Include

Please include the following information in your report:

- **Description**: A clear description of the vulnerability
- **Impact**: What could an attacker do with this vulnerability?
- **Steps to Reproduce**: Detailed steps to reproduce the issue
- **Affected Components**: Which parts of the system are affected
- **Suggested Fix**: If you have ideas on how to fix it (optional)
- **Environment**: OS, Docker version, Python version, etc.

### 4. Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Varies based on severity
  - Critical: Within 7 days
  - High: Within 14 days
  - Medium: Within 30 days
  - Low: Within 60 days

## Security Best Practices

### For Users

1. **Change Default Credentials**
   - Always change `WORKER_API_KEY`, `FLASK_SECRET`, and `ARIA2_RPC_SECRET`
   - Use strong, random passwords for `LOGIN_USERS`

2. **Use HTTPS**
   - Always use HTTPS in production
   - Consider using a reverse proxy like nginx with Let's Encrypt

3. **Keep Dependencies Updated**
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

4. **Restrict Access**
   - Use firewall rules to restrict access to the API port (9731)
   - Only expose the frontend port (9732) to trusted networks
   - Consider using VPN or SSH tunneling for remote access

5. **Monitor Logs**
   ```bash
   docker-compose logs -f
   ```

6. **Regular Backups**
   - Backup your database regularly
   - Store backups securely and test restoration

### For Developers

1. **Input Validation**
   - All user inputs must be validated
   - Use Pydantic models for API request validation
   - Sanitize file paths to prevent path traversal

2. **Authentication**
   - API endpoints must require authentication
   - Use secure session management in frontend
   - Implement rate limiting

3. **Dependencies**
   - Run `pip-audit` and `safety check` before releases
   - Keep dependencies up to date
   - Review dependency changes in PRs

4. **Code Review**
   - All code changes require review
   - Security-sensitive changes require extra scrutiny
   - Run linters and tests before merging

5. **Secrets Management**
   - Never commit secrets to version control
   - Use environment variables for sensitive data
   - Validate that default secrets are not used in production

## Known Security Considerations

### 1. AllDebrid API Key

The AllDebrid API key has full access to your account. Protect it carefully:
- Never share your `.env` file
- Never commit `.env` to version control
- Rotate keys regularly if exposed
- Use environment-specific keys (dev/staging/production)

### 2. File Access

Downloaded files are served through the frontend:
- Access is protected by authentication
- Implement rate limiting to prevent abuse
- Consider using nginx X-Accel-Redirect for better performance

### 3. Storage Permissions

Ensure proper file system permissions:
```bash
chmod 700 /srv/storage
chown 1000:1000 /srv/storage  # Match Docker user
```

### 4. Database Security

- Use strong PostgreSQL passwords
- Don't expose database port externally
- Enable SSL for database connections in production
- Regular backups with encryption

### 5. Redis Security

- Don't expose Redis port externally
- Consider using Redis ACLs
- Use a strong password in production

## Dependency Security

We regularly scan dependencies for vulnerabilities using:
- `pip-audit` - Official Python security scanner
- `safety` - Database of known security vulnerabilities
- GitHub Dependabot - Automated dependency updates

Run security checks locally:
```bash
pip install pip-audit safety
pip-audit
safety check
```

## Incident Response

If a security incident occurs:

1. **Assess Impact**: Determine what data/systems are affected
2. **Contain**: Stop the bleeding (disable compromised accounts, etc.)
3. **Investigate**: Review logs to understand what happened
4. **Remediate**: Fix the vulnerability
5. **Notify**: Inform affected users if necessary
6. **Learn**: Update procedures to prevent recurrence

## Security Checklist for Deployment

- [ ] Changed all default credentials
- [ ] Using HTTPS with valid certificate
- [ ] Firewall rules configured
- [ ] Rate limiting enabled
- [ ] Logs being monitored
- [ ] Backups configured and tested
- [ ] Dependencies scanned for vulnerabilities
- [ ] Strong passwords enforced
- [ ] Database not exposed externally
- [ ] Redis not exposed externally

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Flask Security](https://flask.palletsprojects.com/en/2.3.x/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

## Contact

For security-related questions (not vulnerabilities), please open a GitHub Discussion in the Security category.

---

Last Updated: 2025-12-11
