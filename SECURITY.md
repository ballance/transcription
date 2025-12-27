# Security Policy

## Supported Versions

Currently supported versions of the transcription service:

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| 1.x     | :x:                |

## Security Features

### Authentication & Authorization
- API key-based authentication (X-API-Key header)
- Rate limiting: 100 requests per minute per API key
- Secure API key generation and storage

### Data Security
- File size validation (max 500MB by default)
- MIME type validation for uploads
- Automatic cleanup of uploaded files after processing
- Database connection pooling with secure credentials

### Infrastructure Security
- Docker containerization with minimal base images
- Health checks for all services
- No default credentials in production
- Secrets management via environment variables

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability:

1. **DO NOT** open a public GitHub issue
2. **Use GitHub Security Advisories** to privately report security issues:
   - Go to the repository's Security tab
   - Click "Report a vulnerability"
   - Or email: security@[repository-domain] (if configured)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline
- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Based on severity
  - Critical: 24-48 hours
  - High: 1 week
  - Medium: 2 weeks
  - Low: Next release

## Security Best Practices for Deployment

### Production Deployment Checklist

- [ ] Change default database passwords
- [ ] Use secrets management (AWS Secrets Manager, Vault, etc.)
- [ ] Enable HTTPS/TLS for all endpoints
- [ ] Configure proper CORS settings
- [ ] Set up API key rotation policy
- [ ] Enable audit logging
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerting
- [ ] Regular dependency updates (use Dependabot)
- [ ] Enable PostgreSQL SSL connections
- [ ] Configure Redis AUTH
- [ ] Set proper file permissions in containers
- [ ] Use non-root users in Docker containers
- [ ] Enable Docker security scanning
- [ ] Set up backup encryption
- [ ] Configure rate limiting at load balancer level

### Environment Variables Security

Never commit:
- `.env` files
- API keys
- Database passwords
- JWT secrets
- AWS credentials

Use:
- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- Google Secret Manager

### API Security

**Required for Production:**
```python
# Enable authentication
API_KEYS=your-secure-api-key-here

# Enable HTTPS only
FORCE_HTTPS=true

# Configure CORS
CORS_ORIGINS=https://yourdomain.com

# Rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
```

## Known Security Considerations

### Development vs. Production

**Development mode (not secure):**
- No authentication required
- Debug mode enabled
- Sample credentials
- Hot reload enabled

**Production mode (secure):**
- API key authentication required
- Debug mode disabled
- Secure secrets from secret manager
- Optimized builds

### Third-Party Dependencies

We monitor dependencies for vulnerabilities using:
- GitHub Dependabot
- Safety (Python package security scanner)
- Trivy (container scanning)

Regular updates are applied monthly or immediately for critical vulnerabilities.

## Security Updates

Subscribe to security updates:
- Watch this repository for security advisories
- Check releases for security patches
- Review CHANGELOG for security-related changes

## Compliance

### Data Handling
- Audio files are processed and stored temporarily
- Transcriptions are stored in PostgreSQL
- GDPR: Implement data retention and deletion policies
- HIPAA: Additional encryption and audit logging required

### Audit Trail
All API requests are logged with:
- Timestamp
- API key (hashed)
- Endpoint accessed
- Request ID
- Response status

## Security Contacts

For security-related inquiries:
- **GitHub Security Advisories**: Use the repository's Security tab to report vulnerabilities privately
- **General Questions**: Open a GitHub Discussion for non-sensitive security questions
- **Project Maintainers**: Contact repository maintainers through GitHub for security coordination

For organizations deploying this service in production, configure your own security contacts in this section.
