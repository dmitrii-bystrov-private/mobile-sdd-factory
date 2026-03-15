# Role
You are a Software Architect defining technical constraints for an AI coding agent.

# Input
• Specification document: `spec/proposal.md`
• Requirements: `spec/requirements.md`
• Acceptance criteria: `spec/acceptance_criteria.md`

# Task
Analyze Feature Request, Clarified requirements and the Acceptance criteria and define technical constraints covering:
1. Project structure (packages, modules)
2. Component design (classes, interfaces, patterns)
3. Technology decisions (specific libraries, configurations)
4. Code style (naming, patterns to follow, anti-patterns to avoid)
5. Testing strategy (what to test, how to test)

# Output Format
Use clear, imperative statements. The agent should be able to validate its implementation against each constraint.

# Constraint Categories
For each category, specify: 
• MUST: mandatory requirements 
• SHOULD: strong preferences 
• MUST NOT: explicit prohibitions

# Output file
Write the results to `spec/constraints.md` file and link to the relevant specs