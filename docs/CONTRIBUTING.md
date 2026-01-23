# Contributing

Thanks for your interest in improving Job Bot. This guide covers adding new boards, improving existing ones, and contributing code.

## Adding a New Board

### 1. Create Board Directory

Copy an existing board as a template:

```bash
cp -r boards/indeed boards/newboard
```

### 2. Update Configuration

Edit `boards/newboard/config/settings.yaml`:

```yaml
search:
  job_boards: ["newboard"]  # Change this
  keywords:
    - "your keywords"
  location: "your location"
  # ... rest of config
```

### 3. Setup Browser Profile

```bash
export JOB_BOT_BOARD="newboard"
python3 shared/setup_session.py
```

Solve any captcha that appears, press Enter to save session.

### 4. Implement Selectors

Edit `boards/newboard/src/collector.py`:

**Required Methods:**

```python
def search(self, query: SearchQuery) -> List[Job]:
    """
    Search for jobs and extract basic info.
    Must return list of Job objects with at minimum:
      - title
      - company
      - location
      - link
    """
    pass

def _extract_job_from_card(self, card_elem) -> Optional[Job]:
    """
    Extract job data from a single listing card.
    Board-specific selectors go here.
    """
    pass
```

**Optional Methods:**

```python
def _fetch_salary(self, job_url: str) -> Optional[str]:
    """
    Fetch salary from detail page.
    Only implement after recon (see docs/RECON.md).
    """
    pass

def _fetch_description(self, job_url: str) -> Optional[str]:
    """
    Fetch full job description.
    Only implement after recon.
    """
    pass
```

### 5. Test with Small Sample

```bash
./scripts/test_selectors.sh newboard 5
```

Expected output:
```
📊 Coverage Stats (5 jobs):
Salary: X/5 (X%)
Description: X/5 (X%)
```

### 6. Full Run

```bash
./scripts/run_board.sh newboard
```

Check output:
- `boards/newboard/output/jobs_*.json`
- `boards/newboard/output/jobs_*.md`

### 7. Submit Pull Request

Include:
- Board directory with all files
- Recon documentation (see below)
- Test results showing coverage
- Screenshot of output

## Improving Existing Boards

### Fixing Broken Selectors

Sites change their HTML frequently. If selectors break:

1. **Identify the Problem**
   ```bash
   ./scripts/test_selectors.sh glassdoor 5
   # Check logs
   tail boards/glassdoor/logs/job_bot_*.log
   ```

2. **Inspect Current HTML**
   - Open site in browser
   - Right-click target element → Inspect
   - Note new selector

3. **Update Collector**
   ```python
   # Old selector (broken)
   card.locator('.old-class')

   # New selector
   card.locator('.new-class')
   ```

4. **Test Fix**
   ```bash
   ./scripts/test_selectors.sh glassdoor 20
   ```

5. **Submit PR** with before/after test results

### Adding Features (Salary, Descriptions)

Follow the [Recon Methodology](RECON.md):

1. **Phase 1-2**: Document all layout cases
2. **Phase 3**: Implement selector chain
3. **Phase 4**: Test coverage (90%+ required)
4. **Phase 5**: Enable in config

Include your recon documentation in the PR:
```
docs/recon/glassdoor-descriptions.md
docs/recon/screenshots/
```

## Code Guidelines

### Style

Follow existing code style:

- **PEP 8** for Python
- **Type hints** for function signatures
- **Docstrings** for public methods
- **Comments** for complex logic only

### Error Handling

Always use try-except for selectors:

```python
try:
    element = page.locator('.selector')
    if element.count() > 0 and element.is_visible():
        return element.inner_text()
except Exception as e:
    logger.warning(f"Failed to extract X: {e}")
    return None
```

Never let one failed selector break the entire run.

### Logging

Use the logger, don't print directly:

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Starting search for X")
logger.warning("Selector Y not found")
logger.error("Failed to parse Z", exc_info=True)
```

### Testing

Test before submitting:

```bash
# Small sample
./scripts/test_selectors.sh yourboard 5

# Medium sample
./scripts/test_selectors.sh yourboard 20

# Full run
./scripts/run_board.sh yourboard
```

Include test results in PR description.

## Project Structure

```
job-search-automation-agent/
├── boards/<name>/          # Add board-specific code here
│   ├── config/
│   │   └── settings.yaml   # Board config
│   └── src/
│       └── collector.py    # Board-specific selectors
├── shared/                 # Don't modify unless necessary
│   ├── main.py
│   ├── ai_scorer.py
│   └── ...
├── scripts/                # Utility scripts
└── docs/                   # Documentation
```

**When to Modify Shared Code:**

- Adding new config options (update `config_loader.py`)
- Changing data models (update `models.py`)
- Improving AI scoring (update `ai_scorer.py`)
- Fixing core bugs

**When to Add Board-Specific Code:**

- Implementing selectors for new board
- Adding board-specific parsing logic
- Handling board-specific errors

## Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] Coverage is 90%+ (for new features)
- [ ] Documentation is included (recon notes, README updates)
- [ ] Commit messages are clear

### PR Template

```markdown
## Description
Brief description of what this PR does.

## Type of Change
- [ ] New board
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation

## Testing
Describe how you tested this:
- Test command used
- Coverage results
- Screenshots of output

## Recon Documentation
For new features: link to recon notes or attach as files.

## Checklist
- [ ] Code follows project style
- [ ] Tests pass
- [ ] Documentation updated
```

### Review Process

1. Maintainer reviews code and tests
2. Feedback provided if needed
3. Once approved, PR is merged
4. Board added to README status table

## Getting Help

- **Documentation**: Start with [QUICKSTART.md](QUICKSTART.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
- **Recon Help**: See [RECON.md](RECON.md) for detailed methodology
- **Issues**: Open a GitHub issue with your question
- **Bugs**: Include logs, config, and steps to reproduce

## Code of Conduct

- Be respectful and constructive
- Focus on the technical aspects
- Help others learn and improve
- Follow project guidelines

## Recognition

Contributors will be:
- Listed in README contributors section
- Credited in release notes
- Given commit access after 3+ quality PRs

Thank you for contributing to Job Bot!
