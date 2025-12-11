# Contributing to AllDebrid Proxy

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the project and community

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce**
- **Expected vs actual behavior**
- **Environment details** (OS, Docker version, Python version)
- **Logs** (use `docker-compose logs`)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please include:

- **Clear use case**: Why is this enhancement needed?
- **Detailed description**: What should it do?
- **Possible implementation**: Ideas on how to implement it (optional)

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** following our coding standards
4. **Test your changes** thoroughly
5. **Commit with clear messages**: `git commit -m 'Add amazing feature'`
6. **Push to your fork**: `git push origin feature/amazing-feature`
7. **Open a Pull Request**

## Development Setup

### Prerequisites

- Python 3.11 or 3.12
- Docker and Docker Compose
- Git

### Local Development

```bash
# Clone the repository
git clone https://github.com/macery12/AllDebrid_Proxy.git
cd AllDebrid_Proxy

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Copy and configure .env
cp .env.example .env
nano .env

# Start database and Redis
docker-compose up -d db redis

# Run migrations
alembic upgrade head

# Start services locally
# Terminal 1: API
uvicorn app.main:app --reload --port 8080

# Terminal 2: Worker
python -m worker.worker

# Terminal 3: Frontend
python frontend/app.py
```

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/)
- Maximum line length: 120 characters
- Use type hints wherever possible
- Write docstrings for all public functions/classes

### Code Formatting

Use `black` for consistent formatting:

```bash
black app worker frontend
```

### Linting

Use `ruff` for linting:

```bash
ruff check app worker frontend
```

Fix auto-fixable issues:

```bash
ruff check --fix app worker frontend
```

### Type Checking

Use `mypy` for type checking:

```bash
mypy app worker --ignore-missing-imports
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov=worker --cov-report=html

# Run specific test file
pytest tests/test_utils.py

# Run specific test
pytest tests/test_utils.py::TestParseInfohash::test_valid_hex_infohash
```

### Writing Tests

- Write tests for all new features
- Aim for >80% code coverage
- Use descriptive test names
- Follow AAA pattern (Arrange, Act, Assert)

Example:

```python
def test_parse_valid_magnet():
    """Test that valid magnet links are parsed correctly."""
    # Arrange
    magnet = "magnet:?xt=urn:btih:ABC123..."
    
    # Act
    result = parse_infohash(magnet)
    
    # Assert
    assert result is not None
    assert len(result) == 40
```

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:

```
feat(api): add rate limiting to task creation endpoint

Implements rate limiting using slowapi to prevent abuse.
Limited to 10 requests per minute per IP.

Closes #123
```

```
fix(worker): handle aria2 connection timeout

Added retry logic with exponential backoff when aria2
RPC connection fails.

Fixes #456
```

## Pull Request Process

### Before Submitting

1. **Update tests**: Ensure all tests pass
2. **Run linters**: Fix all linting errors
3. **Check types**: Run mypy
4. **Update documentation**: If you changed functionality
5. **Test manually**: Verify your changes work end-to-end

```bash
# Run all checks
black app worker frontend
ruff check app worker frontend
mypy app worker --ignore-missing-imports
pytest tests/ -v --cov=app --cov=worker
```

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Changes Made
- List of specific changes
- With context for each

## Testing
- How did you test this?
- What test cases were added?

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No new warnings
- [ ] Tests added/updated
- [ ] All tests pass
- [ ] Works locally
```

### Review Process

1. **Automated checks** must pass (CI/CD)
2. **Code review** by at least one maintainer
3. **Address feedback** and make requested changes
4. **Approval** from maintainer
5. **Merge** by maintainer

## Documentation

### Code Documentation

- Add docstrings to all public functions/classes
- Use Google-style docstrings
- Include examples for complex functions

Example:

```python
def parse_infohash(magnet: str) -> Optional[str]:
    """
    Extract the infohash from a magnet link.
    
    Args:
        magnet: A magnet link string (e.g., "magnet:?xt=urn:btih:...")
        
    Returns:
        The infohash in lowercase if found, None otherwise.
        
    Example:
        >>> parse_infohash("magnet:?xt=urn:btih:ABC123...")
        "abc123..."
    """
    # Implementation
```

### README Updates

Update README.md when:
- Adding new features
- Changing configuration
- Modifying setup process
- Adding new dependencies

## Security

- Never commit secrets or API keys
- Report security vulnerabilities privately (see SECURITY.md)
- Review code for security implications
- Run security scans: `pip-audit` and `safety check`

## Questions?

- **General questions**: Open a GitHub Discussion
- **Bug reports**: Open a GitHub Issue
- **Security concerns**: See SECURITY.md
- **Feature requests**: Open a GitHub Issue with "enhancement" label

## Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes for significant contributions
- Git commit history

Thank you for contributing! 🎉
