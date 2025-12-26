# Contributing to Transcription Service

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/ballance/transcription.git
   cd transcription
   ```

2. **Set up development environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

4. **Start development services**
   ```bash
   docker-compose up -d postgres redis
   alembic upgrade head
   ```

5. **Run tests**
   ```bash
   pytest
   ```

## Development Workflow

### Branch Naming

- `feature/description` - New features
- `bugfix/description` - Bug fixes
- `hotfix/description` - Critical production fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Commit Messages

Follow conventional commits:

```
type(scope): description

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

**Examples:**
```
feat(api): add job cancellation endpoint
fix(model-pool): prevent memory leak in LRU eviction
docs(readme): update docker installation steps
test(integration): add API authentication tests
```

### Code Style

**Python Code:**
- Follow PEP 8
- Use Black for formatting (line length: 100)
- Use isort for import sorting
- Type hints for public functions
- Docstrings for all public functions (Google style)

**Run formatters:**
```bash
black .
isort .
flake8 .
mypy .
```

### Testing Requirements

All contributions must include tests:

**Unit Tests** (`tests/unit/`):
- Test individual functions/classes
- Mock external dependencies
- Fast execution (< 1s per test)
- High coverage (aim for 80%+)

**Integration Tests** (`tests/integration/`):
- Test API endpoints
- Test database operations
- Test Celery tasks
- Use test fixtures

**E2E Tests** (`tests/e2e/`):
- Test complete workflows
- Test Docker Compose stack
- Slower but comprehensive

**Running tests:**
```bash
# All tests
pytest

# Specific category
pytest tests/unit
pytest tests/integration -m integration

# With coverage
pytest --cov=. --cov-report=html

# Watch mode during development
pytest --watch
```

## Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes**
   - Write code
   - Add tests
   - Update documentation
   - Run linters and tests locally

3. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat(scope): description"
   ```

4. **Push and create PR**
   ```bash
   git push origin feature/my-feature
   ```
   Then create a pull request on GitHub

5. **PR Requirements**
   - [ ] Tests pass in CI
   - [ ] Code coverage maintained or improved
   - [ ] Documentation updated
   - [ ] CHANGELOG.md updated (for user-facing changes)
   - [ ] No security vulnerabilities introduced
   - [ ] Reviewed by at least one maintainer

6. **PR Description Template**
   ```markdown
   ## Description
   Brief description of changes

   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   - [ ] Documentation update

   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests added/updated
   - [ ] Manually tested

   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Self-review completed
   - [ ] Comments added for complex code
   - [ ] Documentation updated
   - [ ] No new warnings generated
   - [ ] Tests pass locally
   ```

## Project Structure

```
transcription/
├── app.py              # FastAPI application
├── worker.py           # Celery worker
├── tasks.py            # Celery tasks
├── models.py           # Database models
├── database.py         # Database connection
├── model_pool.py       # Model pooling
├── auth.py             # Authentication
├── config.py           # Configuration
├── tests/              # Test suite
│   ├── unit/          # Unit tests
│   ├── integration/   # Integration tests
│   └── e2e/           # End-to-end tests
├── migrations/         # Database migrations
├── docs/              # Documentation
└── .github/           # CI/CD workflows
```

## Areas for Contribution

### Good First Issues
- Documentation improvements
- Adding example code
- Improving error messages
- Adding unit tests
- Fixing typos

### Help Wanted
- Performance optimizations
- Security enhancements
- Additional model support
- Monitoring and observability
- Kubernetes deployment manifests

### Advanced
- Speaker diarization
- Multi-language support
- Real-time streaming
- Custom vocabulary
- WebSocket support

## Documentation

- Update README.md for user-facing changes
- Update SETUP.md for installation/configuration changes
- Update agents.md for architecture changes
- Add docstrings to all new functions
- Update API documentation (auto-generated from FastAPI)

## Release Process

1. Version bump in `__init__.py` or `setup.py`
2. Update CHANGELOG.md
3. Create release branch: `release/v2.1.0`
4. Run full test suite
5. Create GitHub release with release notes
6. Deploy to staging
7. Smoke test staging
8. Deploy to production
9. Monitor production metrics

## Questions?

- Open a GitHub issue for bugs or feature requests
- Join discussions for questions
- Email maintainers for sensitive issues

## Recognition

Contributors will be:
- Added to CONTRIBUTORS.md
- Mentioned in release notes
- Thanked in project documentation

Thank you for contributing! 🎉
