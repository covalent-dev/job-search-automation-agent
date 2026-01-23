# Recon Methodology

How to add or improve scrapers for job boards.

## Overview

Job boards use multiple HTML layouts for the same data. A naive selector might work for 30% of jobs. The recon methodology achieves 90%+ coverage by systematically documenting layout variations.

## When to Use Recon

Before enabling any new feature for a board:

- Adding salary extraction
- Adding description extraction
- Updating selectors after site changes
- Adding a completely new board

## The 5-Phase Process

### Phase 1: Layout Identification

**Goal:** Find all distinct HTML structures for the target data.

**Steps:**

1. Open the job board in a browser
2. Search for relevant jobs (use your actual search terms)
3. Manually inspect 20-30 job listings
4. Identify layout patterns

**Example (Glassdoor Salary):**

Visit Glassdoor, search "AI engineer", inspect the first 30 results. You'll notice:

- **Case 0**: Some jobs show salary on the list card
- **Case 1**: Some show salary only on the detail page header
- **Case 2**: Some show salary in a "Pay & Benefits" section
- **Case 3**: Some show no salary anywhere

**Document Your Findings:**

```
Layout Cases for Glassdoor Salary:

Case 0 (40% of jobs): Salary on list card
Case 1 (35% of jobs): Salary on detail header
Case 2 (15% of jobs): Salary in pay section
Case 3 (10% of jobs): No salary
```

### Phase 2: HTML Documentation

**Goal:** For each case, document the exact HTML structure and selectors.

**Tools:**
- Browser DevTools (right-click → Inspect)
- Screenshots
- Copy HTML snippets

**For Each Case:**

1. Find a job that exhibits this case
2. Right-click the target element → Inspect
3. Copy the HTML structure
4. Document the selector
5. Take a screenshot
6. Note the data format

**Example Documentation:**

```markdown
## Case 0: List Card Salary

**HTML Structure:**
```html
<div class="job-card">
  <div class="job-details">
    <div data-test="detailSalary">
      <span>$80K-$100K</span>
    </div>
  </div>
</div>
```

**CSS Selector:**
`[data-test="detailSalary"]`

**XPath Fallback:**
`//div[@data-test="detailSalary"]//span`

**Data Format:**
- Text: "$80K-$100K"
- Pattern: $XXK-$XXXK
- Sometimes: "$80,000 - $100,000"

**Coverage:** ~40% of jobs

**Screenshot:** `recon/glassdoor-salary-case0.png`
```

Repeat for all cases.

### Phase 3: Selector Implementation

**Goal:** Implement selectors that cover all cases.

**Pattern: Selector Chain with Fallbacks**

```python
def _fetch_salary(self, page: Page) -> Optional[str]:
    """Fetch salary using multi-case selector strategy"""

    # Case 0: List card salary
    try:
        salary_elem = page.locator('[data-test="detailSalary"]')
        if salary_elem.count() > 0 and salary_elem.is_visible():
            return self._normalize_salary(salary_elem.inner_text())
    except Exception:
        pass

    # Case 1: Detail header salary
    try:
        salary_elem = page.locator('.salary-estimate')
        if salary_elem.count() > 0 and salary_elem.is_visible():
            return self._normalize_salary(salary_elem.inner_text())
    except Exception:
        pass

    # Case 2: Pay section
    try:
        salary_elem = page.locator('.payPeriod')
        if salary_elem.count() > 0 and salary_elem.is_visible():
            return self._normalize_salary(salary_elem.inner_text())
    except Exception:
        pass

    # Case 3: No salary found
    return None
```

**Key Principles:**

1. **Try-Except Each Case**: Don't let one failed selector break the others
2. **Check Visibility**: Element might exist but not be visible
3. **Normalize Data**: Clean up formatting inconsistencies
4. **Return Early**: Stop at first successful match
5. **Graceful Degradation**: Return None if nothing works

### Phase 4: Testing

**Goal:** Verify coverage matches your recon findings.

**Small Sample Test:**

```bash
./scripts/test_selectors.sh glassdoor 5
```

Expected output:
```
📊 Coverage Stats (5 jobs):
Salary: 5/5 (100%)
Description: 0/5 (0%)
```

If coverage is < 90%, investigate failures:

1. Check logs: `boards/glassdoor/logs/job_bot_*.log`
2. Look for selector errors
3. Add missing cases
4. Test again

**Medium Sample Test:**

```bash
./scripts/test_selectors.sh glassdoor 20
```

Aim for 90%+ coverage on 20 jobs.

### Phase 5: Enable in Config

**Goal:** Turn on the feature for production runs.

Only enable after testing validates coverage:

```yaml
search:
  detail_salary_fetch: true
  detail_salary_max_per_query: 0  # 0 = unlimited
```

**First Production Run:**

```bash
./scripts/run_board.sh glassdoor
```

Monitor the first run:
- Check logs for errors
- Verify coverage in output JSON
- Compare coverage to recon findings

If coverage drops significantly, revisit Phase 2 (document missed cases).

## Recon Checklist

Use this checklist for each recon session:

- [ ] Phase 1: Identified all layout cases (3-5 typical)
- [ ] Phase 2: Documented HTML structure for each case
- [ ] Phase 2: Noted CSS selectors and XPath fallbacks
- [ ] Phase 2: Captured screenshots
- [ ] Phase 2: Documented data formats
- [ ] Phase 3: Implemented selector chain with try-except
- [ ] Phase 3: Added normalization function
- [ ] Phase 4: Tested on 5 jobs (100% coverage)
- [ ] Phase 4: Tested on 20 jobs (90%+ coverage)
- [ ] Phase 4: Reviewed logs for errors
- [ ] Phase 5: Enabled in config
- [ ] Phase 5: Ran full production test
- [ ] Phase 5: Verified output coverage

## Example: Glassdoor Salary Recon

See the full Glassdoor salary recon that achieved 90%+ coverage in:

`Taxman_Progression_v4/04_Tech_and_AI/Job-Bot-Recon-Workflow.md`

This documents:
- All 3 layout cases found
- Exact HTML structures
- Selector implementations
- Test results
- Production validation

## Common Patterns

### Data in JSON-LD

Some sites embed structured data:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "baseSalary": {
    "minValue": 80000,
    "maxValue": 100000
  }
}
</script>
```

Extract with:

```python
json_ld = page.locator('script[type="application/ld+json"]').inner_text()
data = json.loads(json_ld)
salary = data.get('baseSalary', {})
```

### Dynamic Content

Some data loads via JavaScript after page load:

```python
# Wait for element to appear
page.wait_for_selector('.salary', timeout=5000)
salary = page.locator('.salary').inner_text()
```

### Pagination Changes

List pages vs detail pages may have different structures:

```python
def _fetch_salary_from_list(self, card_elem):
    # List page selectors
    pass

def _fetch_salary_from_detail(self, page):
    # Detail page selectors (more complete)
    pass
```

## Tips

### Start Simple
Begin with one feature (e.g., salary) on one board. Master the process before tackling multiple features.

### Use Real Search Terms
Test with your actual keywords. Some layouts only appear for certain job types.

### Document as You Go
Take notes during Phase 1-2. Memory fades quickly.

### Keep Recon Files
Save your recon documentation:
```
docs/recon/
├── glassdoor-salary.md
├── linkedin-description.md
└── screenshots/
    ├── glassdoor-case0.png
    └── glassdoor-case1.png
```

### Test on Fresh Data
Job boards update layouts occasionally. Re-run tests monthly to catch changes early.

### Expect 90%, Not 100%
Some jobs have genuinely missing data. 90%+ coverage is excellent.

## Troubleshooting

### Coverage Dropped After Site Update

Sites change their HTML frequently.

**Fix:**
1. Re-run Phase 1 (identify new cases)
2. Update selectors for changed cases
3. Test again

### Selectors Work in DevTools But Fail in Script

Timing issue - element not loaded yet.

**Fix:**
```python
page.wait_for_selector('.salary', timeout=5000)
```

### Some Cases Not Found in Testing

Your test sample may not include all cases.

**Fix:**
- Increase sample size: `./scripts/test_selectors.sh glassdoor 50`
- Use different search terms to trigger varied layouts

### JSON-LD Missing or Malformed

Some jobs have broken structured data.

**Fix:**
Add fallback to HTML selectors:
```python
try:
    # Try JSON-LD first
    salary = extract_from_json_ld(page)
except:
    # Fallback to HTML
    salary = extract_from_html(page)
```

## Next Steps

Once you've completed recon for one feature on one board:

1. **Document Your Process**: Add to `docs/recon/`
2. **Update Board Status**: Mark feature as ✅ in README
3. **Test in Production**: Run full board for validation
4. **Apply to Other Boards**: Use the same methodology
5. **Share Learnings**: Update this guide with new patterns

The recon methodology is the foundation of reliable scraping. Time invested in thorough recon pays off in stable, high-coverage extractors.
