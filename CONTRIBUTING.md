# Contributing

Thanks for your interest in contributing to Finance Skills! This guide will help you
add new skills or improve existing ones.

## Requesting a Skill

You can suggest new skills by
[opening an issue](https://github.com/JoelLewis/finance_skills/issues/new) with:
- The domain/plugin it belongs to
- A brief description of what the skill would teach Claude
- Example use cases or trigger phrases

## Adding a New Skill

### 1. Choose the right plugin

Skills belong to one of seven plugins. Check [PLAN.md](PLAN.md) for the full list
and planned skills.

| Plugin | Domain | Skill type |
|--------|--------|------------|
| `core` | Math foundations | Quantitative (Python scripts) |
| `wealth-management` | Investment knowledge | Quantitative (Python scripts for risk/math) |
| `compliance` | US securities regulation | Guidance-only (no scripts) |
| `advisory-practice` | Advisor-facing systems | Guidance-only |
| `trading-operations` | Order lifecycle and execution | Guidance-only |
| `client-operations` | Account lifecycle and servicing | Guidance-only |
| `data-integration` | Reference data and integration | Guidance-only |

### 2. Create the skill directory

```bash
mkdir -p plugins/<plugin-name>/skills/<skill-name>
```

Directory names use `lowercase-hyphenated` format (e.g., `fixed-income-sovereign`).

### 3. Write the SKILL.md

Every skill needs a `SKILL.md` with YAML frontmatter:

```yaml
---
name: <skill-name>
description: <one-line description — include trigger phrases for skill matching>
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---
```

The `name` field must match the directory name exactly.

### 4. Follow the template

All skills share a common structure (see [PLAN.md](PLAN.md) for the full template):

- **Purpose** — what the skill enables Claude to do
- **When to Use** — trigger phrases and situations
- **Core Concepts** — the domain knowledge
- **Worked Examples** — concrete scenarios with analysis
- **Common Pitfalls** — mistakes to watch for
- **Cross-References** — links to related skills in other plugins

**Quantitative skills** (core, wealth-management) additionally include:
- **Key Formulas** — reference table with expressions and use cases
- **Reference Implementation** — pointer to Python script in `scripts/`

**Guidance-only skills** (compliance, operations) use scenario-based examples:
- **Scenario** / **Compliance Issues** / **Analysis** format
- Cite specific rule numbers and act sections inline
- Do not include Key Formulas or Reference Implementation sections

### 5. Add Python scripts (quantitative skills only)

Only `core` and `wealth-management` skills get Python scripts. Scripts should:
- Target Python 3.11+ with only numpy/scipy/pandas dependencies
- Be standalone (runnable without installation)
- Use class-based organization with static methods
- Include type hints and docstrings
- Match the formulas documented in the corresponding SKILL.md
- Use `lowercase_underscore` naming (e.g., `fixed_income_sovereign.py`)

```
plugins/<plugin-name>/skills/<skill-name>/
├── SKILL.md           # Required
└── scripts/           # Quantitative skills only
    └── <name>.py
```

### 6. Add cross-references

Update the Cross-References section in both the new skill and any related existing
skills. Cross-references should include the plugin name and a brief description of
the relationship.

## Improving Existing Skills

1. Read the existing skill thoroughly
2. Keep changes focused and minimal
3. Ensure compliance skills still cite specific rule numbers
4. Ensure quantitative skills still have matching formulas in SKILL.md and scripts
5. Update cross-references if the change affects related skills

## Submitting Your Contribution

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-skill-name`)
3. Make your changes
4. Test locally with Claude Code to verify the skill works
5. Submit a pull request with a description of what the skill teaches

## Quality Checklist

- [ ] `name` in frontmatter matches directory name
- [ ] `description` clearly explains when to use the skill
- [ ] Skill follows the correct template (quantitative vs guidance-only)
- [ ] Worked examples are concrete and include step-by-step analysis
- [ ] Cross-references are added in both directions
- [ ] No sensitive data or credentials
- [ ] Compliance skills cite specific rule numbers
- [ ] Python scripts (if any) are standalone and match SKILL.md formulas

## Questions?

Open an issue if you have questions or need help with your contribution.
